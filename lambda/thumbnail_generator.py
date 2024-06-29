import logging
import boto3
from io import BytesIO
from PIL import Image
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

def lambda_handler(event, context):
    logger.info(f"event: {event}")
    logger.info(f"context: {context}")

    # Get the S3 bucket and object key from the event
    bucket = event["Records"][0]["s3"]["bucket"]["name"]
    key = event["Records"][0]["s3"]["object"]["key"]

    # Define the destination bucket and thumbnail key
    thumbnail_bucket = os.environ['DEST_BUCKET']
    thumbnail_name, thumbnail_ext = os.path.splitext(key)
    thumbnail_key = f"{thumbnail_name}_thumbnail{thumbnail_ext}"

    logger.info(f"Bucket name: {bucket}, file name: {key}, Thumbnail Bucket name: {thumbnail_bucket}, file name: {thumbnail_key}")

    # Open the image using Pillow
    file_byte_string = s3_client.get_object(Bucket=bucket, Key=key)['Body'].read()
    img = Image.open(BytesIO(file_byte_string))
    logger.info(f"Size before compression: {img.size}")

    # Create a thumbnail
    img.thumbnail((500,500))
    logger.info(f"Size after compression: {img.size}")

    # Save the thumbnail to a BytesIO object
    buffer = BytesIO()
    img.save(buffer, "JPEG")
    buffer.seek(0)

    # Upload the thumbnail to the destination bucket
    sent_data = s3_client.put_object(Bucket=thumbnail_bucket, Key=thumbnail_key, Body=buffer)

    if sent_data['ResponseMetadata']['HTTPStatusCode'] != 200:
        raise Exception('Failed to upload image {} to bucket {}'.format(key, bucket))

    return event
