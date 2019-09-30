"""Example Airflow DAG that creates a Cloud Dataproc cluster, runs the Hadoop
wordcount example, and deletes the cluster.

This DAG relies on three Airflow variables
https://airflow.apache.org/concepts.html#variables
* gcp_project - Google Cloud Project to use for the Cloud Dataproc cluster.
* gce_zone - Google Compute Engine zone where Cloud Dataproc cluster should be
  created.
* gcs_bucket - Google Cloud Storage bucket to use for result of Hadoop job.
  See https://cloud.google.com/storage/docs/creating-buckets for creating a
  bucket.
"""

import datetime
import os

from airflow import models
from airflow.contrib.operators.gcs_operator import GoogleCloudStorageCreateBucketOperator
from airflow.contrib.operators.gcs_to_gcs import GoogleCloudStorageToGoogleCloudStorageOperator
from airflow.contrib.operators.gcs_to_bq import GoogleCloudStorageToBigQueryOperator
from airflow.contrib.operators.bigquery_operator import BigQueryCreateEmptyDatasetOperator


# To start DAG directly when detected
YESTERDAY = datetime.datetime.now() - datetime.timedelta(days=1)
PROJECT = models.Variable.get('gcp_project')
BUCKET = models.Variable.get('gcs_bucket')
REGION = models.Variable.get('gce_zone')
LAB_ID = BUCKET.replace('-', '_').replace('.', '_')
DATASET = 'instacart_{LAB_ID}'.format(LAB_ID=LAB_ID)

default_dag_args = {
    # Setting start date as yesterday starts the DAG immediately when it is
    # detected in the Cloud Storage bucket.
    'start_date': YESTERDAY,
    # To email on failure or retry set 'email' arg to your email and enable
    # emailing here.
    'email_on_failure': False,
    'email_on_retry': False,
    # If a task fails, retry it once after waiting at least 5 minutes
    'retries': 0,
    'retry_delay': datetime.timedelta(minutes=5),
    'project_id': PROJECT,
}


def get_create_bucket_task():
    return GoogleCloudStorageCreateBucketOperator(
        task_id='create_bucket',
        bucket_name=BUCKET,
    )


def get_copy_csv_tasks():
    return GoogleCloudStorageToGoogleCloudStorageOperator(
        task_id='copy_csv_files',
        source_bucket='avaus-academy-bucket',
        source_object='instacart/*',
        destination_bucket=BUCKET,
        destination_object='instacart/',
    )


def get_create_dataset_task():
    return BigQueryCreateEmptyDatasetOperator(
        task_id='create_dataset',
        project_id=PROJECT,
        dataset_id=DATASET,
    )


def get_csv_to_bigquery_tasks():
    csv_files = [
        'aisles.csv',
        'departments.csv',
        'order_products__prior.csv',
        'order_products__train.csv',
        'orders.csv',
        'products.csv',
    ]
    return [
        GoogleCloudStorageToBigQueryOperator(
            task_id='csv_to_bigquery_{CSV}'.format(CSV=csv),
            bucket=BUCKET,
            source_objects=['instacart/{CSV}'.format(CSV=csv)],
            destination_project_dataset_table='{PROJECT}:{DATASET}.{TABLE}'.format(PROJECT=PROJECT, DATASET=DATASET, TABLE=csv.split('.')[0]),
            autodetect=True,
            skip_leading_rows=1,
        ) for csv in csv_files
    ]

with models.DAG(
    'ml_pipeline',
    schedule_interval=datetime.timedelta(days=1),
    default_args=default_dag_args,
) as dag:

    tasks = []

    # Create a bucket
    #tasks.append(get_create_bucket_task())

    # Copy csv files to bucket
    #tasks.append(get_copy_csv_tasks())

    # Create a dataset
    #tasks.append(get_create_dataset_task())

    # Copy csv to bigquery table
    tasks.extend(get_csv_to_bigquery_tasks())

    # Generate dependency
    task = tasks[0]

    if len(tasks) == 1:
        task
    else:
        for i in range(1, len(tasks)):
            task >> tasks[i]
            task = tasks[i]
