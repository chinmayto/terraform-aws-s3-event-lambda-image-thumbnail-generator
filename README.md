# Creating an Image Thumbnail Generator Using AWS Lambda and S3 Event Notifications with Terraform
Creating an Image Thumbnail Generator Using AWS Lambda and S3 Event Notifications with Terraform

In this post, we'll explore how to use serverless Lambda functions to create an image thumbnail generator triggered by S3 event notifications, all orchestrated using Terraform.

## Architecture Overview
Before we get started, let's take a quick look at the architecture we'll be working with:
![alt text](/images/diagram.png)


## Step 1: Create Source and Destination Buckets
First, we'll create two S3 buckets: one for the source images and another for the generated thumbnails.

```hcl
################################################################################
# S3 Source Image Bucket
################################################################################
resource "aws_s3_bucket" "source-image-bucket" {
  bucket = var.source_bucket_name
  tags = merge(local.common_tags, {
    Name = "${local.naming_prefix}-s3-source-bucket"
  })
}

################################################################################
# S3 Thumbnail Image Bucket
################################################################################
resource "aws_s3_bucket" "thumbnail-image-bucket" {
  bucket = var.thumbnail_bucket_name
  tags = merge(local.common_tags, {
    Name = "${local.naming_prefix}-s3-thumbnail-bucket"
  })
}
```

## Step 2: Create a Policy
Next, we create a policy that grants permissions for the Lambda function to read from the source bucket and write to the destination bucket.
```hcl
################################################################################
# S3 Policy to Get and Put objects
################################################################################
resource "aws_iam_policy" "lambda_s3_policy" {
  name = "LambdaS3Policy"
  policy = jsonencode({
    "Version" : "2012-10-17",
    "Statement" : [{
      "Effect" : "Allow",
      "Action" : "s3:GetObject",
      "Resource" : "${aws_s3_bucket.source-image-bucket.arn}/*"
      }, {
      "Effect" : "Allow",
      "Action" : "s3:PutObject",
      "Resource" : "${aws_s3_bucket.thumbnail-image-bucket.arn}/*"
    }]
  })
}
```

## Step 3: Create a Lambda AssumeRole
Attach the created policy along with the AWSLambdaBasicExecutionRole to a new IAM role.
```hcl
################################################################################
# Lambda IAM role to assume the role
################################################################################
resource "aws_iam_role" "lambda_s3_role" {
  name = "LambdaS3Role"
  assume_role_policy = jsonencode({
    "Version" : "2012-10-17",
    "Statement" : [{
      "Effect" : "Allow",
      "Principal" : {
        "Service" : "lambda.amazonaws.com"
      },
      "Action" : "sts:AssumeRole"
    }]
  })
}

################################################################################
# Assign policy to the role
################################################################################
resource "aws_iam_policy_attachment" "assigning_policy_to_role" {
  name       = "AssigingPolicyToRole"
  roles      = [aws_iam_role.lambda_s3_role.name]
  policy_arn = aws_iam_policy.lambda_s3_policy.arn
}

resource "aws_iam_policy_attachment" "assigning_lambda_execution_role" {
  name       = "AssigningLambdaExecutionRole"
  roles      = [aws_iam_role.lambda_s3_role.name]
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
```

## Step 4: Create a Lambda Function
Write python code for image processing and zip it first. Then, create a Lambda function using Python, incorporating Lambda Layers from Klayers, and add the necessary permissions. We have used python 3.12 runtime environment. User environment vairable DEST_BUCKET to read destination bucket name in code.
```hcl
################################################################################
# Compressing lambda_handler function code
################################################################################
data "archive_file" "thumbnail_lambda_source_archive" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda_function.zip"
}

################################################################################
# Creating Lambda Function
################################################################################
resource "aws_lambda_function" "create_thumbnail_lambda_function" {
  function_name = "CreateThumbnailLambdaFunction"
  filename      = "${path.module}/lambda_function.zip"

  runtime     = "python3.12"
  handler     = "thumbnail_generator.lambda_handler"
  memory_size = 256
  timeout     = 300

  environment {
    variables = {
      DEST_BUCKET = aws_s3_bucket.thumbnail-image-bucket.bucket
    }
  }

  source_code_hash = data.archive_file.thumbnail_lambda_source_archive.output_base64sha256

  role = aws_iam_role.lambda_s3_role.arn

  layers = [
    "arn:aws:lambda:us-east-1:770693421928:layer:Klayers-p312-Pillow:2"
  ]
}

################################################################################
# Lambda Function Permission to have S3 as a Trigger for Lambda Function
################################################################################
resource "aws_lambda_permission" "thumbnail_allow_bucket" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_thumbnail_lambda_function.arn
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.source-image-bucket.arn
}
```

## Step 5: Create S3 Event Notification
Set up an S3 event notification to trigger the Lambda function when a new image is uploaded.
```hcl
################################################################################
# Creating S3 Notification for Lambda when Object is uploaded in the Source Bucket
################################################################################
resource "aws_s3_bucket_notification" "thumbnail_notification" {
  bucket = aws_s3_bucket.source-image-bucket.id
  lambda_function {
    lambda_function_arn = aws_lambda_function.create_thumbnail_lambda_function.arn
    events              = ["s3:ObjectCreated:*"]
  }
  depends_on = [
    aws_lambda_permission.thumbnail_allow_bucket
  ]
}
```

## Step 6: Create CloudWatch Log Group
Finally, create a CloudWatch log group to capture logs from the Lambda function.
```hcl
################################################################################
# Creating CloudWatch Log group for Lambda Function
################################################################################
resource "aws_cloudwatch_log_group" "create_thumbnail_lambda_function_cloudwatch" {
  name              = "/aws/lambda/${aws_lambda_function.create_thumbnail_lambda_function.function_name}"
  retention_in_days = 30
}

```

## Step 7: Write python code for lambda function

1. Dependencies: The function uses boto3 to interact with AWS S3 and Pillow for image processing. We have used existing Layer for Pillow from Klayers using ARN.

2. Event Handling: The function extracts the source bucket and object key from the event triggered by the S3 upload.

3. Environment Variable: The destination bucket is retrieved from the environment variable DEST_BUCKET.

4. Image Processing:
    1) The image is downloaded from the source bucket.
    2) A thumbnail is created using Pillow's thumbnail method.
    3) The thumbnail is saved to a BytesIO object to prepare it for upload.
    4) Uploading the Thumbnail: The thumbnail is uploaded to the destination bucket.

```python
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

```

If you dont want to use the Klayers lambda layers, you can create the package python codes along with dependencies using following.
```sh
mkdir package
pip install pillow -t package/
cp thumbnail_generator.py package/
cd package
zip -r ../lambda_function.zip .
cd ..
```

## Steps to Run Terraform
Follow these steps to execute the Terraform configuration:
```hcl
terraform init
terraform plan 
terraform apply -auto-approve
```

Upon successful completion, Terraform will provide relevant outputs.
```hcl
Apply complete! Resources: 10 added, 0 changed, 0 destroyed.
```

## Testing
Source and Destination S3 buckets
![alt text](/images/s3buckets.png)

Lambda S3 Role with attached policies
![alt text](/images/lambdas3role.png)
![alt text](/images/lambdas3role2.png)
![alt text](/images/lambdas3role3.png)

Lambda Function with runtime settings and layers
![alt text](/images/lambda.png)
![alt text](/images/lambdaproperties.png)

Uploading an image to source bucket with large size
![alt text](/images/imageupload.png)

Thumbnail created in destination bucket with small size
![alt text](/images/thumbnailcreation.png)

Cloudwatch Log group showing the lambda function logs
![alt text](/images/cloudwatchlogs.png)

## Cleanup
Remember to stop AWS components to avoid large bills. Empty the buckets first.
```hcl
terraform destroy -auto-approve
```

## Conclusion
We have successfully used S3 Event notifications to trigger a Lambda function that generates image thumbnails. This serverless architecture ensures scalability and ease of maintenance.

Happy Coding!

## Resources
AWS S3 Notifications https://docs.aws.amazon.com/AmazonS3/latest/userguide/EventNotifications.html

AWS Lambda: https://docs.aws.amazon.com/lambda/latest/dg/welcome.html

Lambda Layers: https://docs.aws.amazon.com/lambda/latest/dg/chapter-layers.html

Klayers: https://github.com/keithrozario/Klayers/tree/master

Tutorial: https://docs.aws.amazon.com/lambda/latest/dg/with-s3-tutorial.html

Github Link: https://github.com/chinmayto/terraform-aws-s3-event-image-thumbnail-generator