"""LocalStack "ready" hook: packages and deploys the project's compute_size Lambda.

LocalStack runs every .py file under /etc/localstack/init/ready.d with its
own bundled Python once the S3/Lambda providers are up, so this needs no
executable bit (which Windows bind mounts wouldn't preserve anyway) and no
extra dependencies beyond what LocalStack already ships (boto3).

Re-running this (e.g. on `docker compose restart localstack`) is safe: it
updates the existing function instead of failing on "already exists".
"""

import io
import os
import shutil
import zipfile

import boto3
from botocore.exceptions import ClientError

ENDPOINT_URL = "http://localhost:4566"
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("S3_BUCKET_NAME", "project-documents")
INTERNAL_SHARED_SECRET = os.environ.get("INTERNAL_SHARED_SECRET", "")
SOURCE_ROOT = "/etc/localstack/lambdas"
BUILD_ROOT = "/tmp/lambda-build"
ROLE_ARN = "arn:aws:iam::000000000000:role/lambda-role"
LAMBDA_PYTHON_VERSION = "3.12"  # must match the Runtime passed to create_function below


def client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def build_zip(name: str) -> bytes:
    source_dir = os.path.join(SOURCE_ROOT, name)
    build_dir = os.path.join(BUILD_ROOT, name)
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir)
    for filename in os.listdir(source_dir):
        if filename.endswith(".py"):
            shutil.copy(os.path.join(source_dir, filename), build_dir)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(build_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                archive.write(full_path, os.path.relpath(full_path, build_dir))
    return buffer.getvalue()


def deploy(lambda_client, name: str, environment: dict[str, str]) -> str:
    zip_bytes = build_zip(name)

    try:
        lambda_client.get_function(FunctionName=name)
        lambda_client.update_function_code(FunctionName=name, ZipFile=zip_bytes)
        lambda_client.update_function_configuration(
            FunctionName=name, Environment={"Variables": environment}
        )
    except lambda_client.exceptions.ResourceNotFoundException:
        lambda_client.create_function(
            FunctionName=name,
            Runtime=f"python{LAMBDA_PYTHON_VERSION}",
            Handler="handler.handler",
            Role=ROLE_ARN,
            Code={"ZipFile": zip_bytes},
            Timeout=30,
            Environment={"Variables": environment},
        )

    lambda_client.get_waiter("function_active_v2").wait(FunctionName=name)

    try:
        lambda_client.add_permission(
            FunctionName=name,
            StatementId="s3invoke",
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:aws:s3:::{BUCKET}",
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass  # permission already granted by a previous run

    return lambda_client.get_function(FunctionName=name)["Configuration"]["FunctionArn"]


def ensure_bucket(s3_client) -> None:
    """Create the bucket if nothing has yet — this hook must not depend on the
    api container being up (e.g. CI only starts db+localstack for testing).
    If the api container *does* win the race and creates it first, that's
    fine too; head_bucket succeeding is enough.
    """
    try:
        s3_client.head_bucket(Bucket=BUCKET)
        return
    except Exception:  # noqa: BLE001 - bucket-not-found errors vary by client
        pass

    try:
        s3_client.create_bucket(Bucket=BUCKET)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise


def main() -> None:
    lambda_client = client("lambda")
    s3_client = client("s3")

    ensure_bucket(s3_client)

    compute_size_arn = deploy(
        lambda_client,
        "compute_size",
        {
            "INTERNAL_API_URL": "http://api:8000",
            "INTERNAL_SHARED_SECRET": INTERNAL_SHARED_SECRET,
        },
    )

    s3_client.put_bucket_notification_configuration(
        Bucket=BUCKET,
        NotificationConfiguration={
            "LambdaFunctionConfigurations": [
                {
                    "Id": "compute-size-on-upload",
                    "LambdaFunctionArn": compute_size_arn,
                    "Events": ["s3:ObjectCreated:*"],
                    "Filter": {"Key": {"FilterRules": [{"Name": "prefix", "Value": "projects/"}]}},
                },
            ]
        },
    )

    print("[lambda-init] compute_size deployed and wired to S3 notifications")


# LocalStack's Python init-hook runner does exec(source, {}) with an empty
# globals dict, so `__name__` is never "__main__" here — an `if __name__ ==
# "__main__"` guard would make main() silently never run. Call it directly.
main()
