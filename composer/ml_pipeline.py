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

from google.cloud import bigquery
from airflow import models
from airflow.contrib.operators.gcs_operator import GoogleCloudStorageCreateBucketOperator
from airflow.contrib.operators.gcs_to_gcs import GoogleCloudStorageToGoogleCloudStorageOperator
from airflow.contrib.operators.gcs_to_bq import GoogleCloudStorageToBigQueryOperator
from airflow.contrib.operators.bigquery_operator import BigQueryCreateEmptyDatasetOperator
from airflow.contrib.operators.bigquery_operator import BigQueryOperator


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
            destination_project_dataset_table='{PROJECT}:{DATASET}.{TABLE}'.format(
                PROJECT=PROJECT,
                DATASET=DATASET,
                TABLE=csv.split('.')[0]
            ),
            autodetect=True,
            skip_leading_rows=1,
        ) for csv in csv_files
    ]


def get_create_user_features_sql():
    return (
        'create_user_features',
        """
        CREATE TABLE instacart_{LAB_ID}.user_features AS
        SELECT
            user_id,
            COUNT(order_id) AS nr_orders,
            SUM(days_since_prior_order) AS user_lifetime,
            COALESCE(COUNT(order_id) / NULLIF(SUM(days_since_prior_order), 0), 1) AS nr_orders_per_day,
            AVG(days_since_prior_order) AS avg_nr_days_between_orders,
            COUNT(CASE WHEN order_dow = 0 THEN order_id END) AS nr_orders_saturday,
            COUNT(CASE WHEN order_dow = 1 THEN order_id END) AS nr_orders_sunday,
            COUNT(CASE WHEN order_dow = 2 THEN order_id END) AS nr_orders_monday,
            COUNT(CASE WHEN order_dow = 3 THEN order_id END) AS nr_orders_tuesday,
            COUNT(CASE WHEN order_dow = 4 THEN order_id END) AS nr_orders_wednesday,
            COUNT(CASE WHEN order_dow = 5 THEN order_id END) AS nr_orders_thursday,
            COUNT(CASE WHEN order_dow = 6 THEN order_id END) AS nr_orders_friday,
            COUNT(CASE WHEN order_hour_of_day BETWEEN 5 AND 11 THEN order_id END) AS nr_orders_morning,
            COUNT(CASE WHEN order_hour_of_day BETWEEN 12 AND 17 THEN order_id END) AS nr_orders_afternoon,
            COUNT(CASE WHEN order_hour_of_day BETWEEN 18 AND 22 THEN order_id END) AS nr_orders_evening,
            COUNT(CASE WHEN order_hour_of_day > 22 OR order_hour_of_day < 5 THEN order_id END) AS nr_orders_night
        FROM instacart_{LAB_ID}.orders
        WHERE eval_set = 'prior' -- Only use the prior data for training features
        GROUP BY
                user_id
        """.format(LAB_ID=LAB_ID)
    )


def get_create_latest_transaction_sql():
    return (
        'create_latest_transaction',
        """
        CREATE TABLE instacart_{LAB_ID}.latest_transaction AS
        SELECT
            user_id,
            ROW_NUMBER() OVER(PARTITION BY user_id ORDER BY order_number DESC) AS order_rank,
            days_since_prior_order,
            CASE WHEN order_dow = 0 THEN 1 ELSE 0 END AS is_saturday_order,
            CASE WHEN order_dow = 1 THEN 1 ELSE 0 END AS is_sunday_order,
            CASE WHEN order_dow = 2 THEN 1 ELSE 0 END AS is_monday_order,
            CASE WHEN order_dow = 3 THEN 1 ELSE 0 END AS is_tuesday_order,
            CASE WHEN order_dow = 4 THEN 1 ELSE 0 END AS is_wednesday_order,
            CASE WHEN order_dow = 5 THEN 1 ELSE 0 END AS is_thursday_order,
            CASE WHEN order_dow = 6 THEN 1 ELSE 0 END AS is_friday_order,
            CASE WHEN order_hour_of_day BETWEEN 5 AND 11 THEN 1 ELSE 0 END AS is_morning_order,
            CASE WHEN order_hour_of_day BETWEEN 12 AND 17 THEN 1 ELSE 0 END AS is_afternoon_order,
            CASE WHEN order_hour_of_day BETWEEN 18 AND 22 THEN 1 ELSE 0 END AS is_evening_order,
            CASE WHEN order_hour_of_day > 22 OR order_hour_of_day < 5 THEN 1 ELSE 0 END AS is_night_order
        FROM instacart_{LAB_ID}.orders
        WHERE eval_set = 'prior'
        """.format(LAB_ID=LAB_ID)
    )


def get_create_feature_set_sql():
    return (
        'create_feature_set',
        """
        CREATE TABLE instacart_{LAB_ID}.feature_set AS
        SELECT
            -- Observation key
            lt.user_id,

            -- Features about last order
            lt.is_saturday_order,
            lt.is_sunday_order,
            lt.is_monday_order,
            lt.is_tuesday_order,
            lt.is_wednesday_order,
            lt.is_thursday_order,
            lt.is_friday_order,
            lt.is_morning_order,
            lt.is_afternoon_order,
            lt.is_evening_order,
            lt.is_night_order,
            lt.days_since_prior_order,

            -- Features about user
            uf.nr_orders,
            uf.user_lifetime,
            uf.nr_orders_per_day,
            uf.avg_nr_days_between_orders,
            uf.nr_orders_saturday,
            uf.nr_orders_sunday,
            uf.nr_orders_monday,
            uf.nr_orders_tuesday,
            uf.nr_orders_wednesday,
            uf.nr_orders_thursday,
            uf.nr_orders_friday,
            uf.nr_orders_morning,
            uf.nr_orders_afternoon,
            uf.nr_orders_evening,
            uf.nr_orders_night,

            -- Target label
            target.days_since_prior_order AS days_to_next_order,

            -- Train vs test
            RAND() <= 0.8 AS is_train
        FROM instacart_{LAB_ID}.latest_transaction lt
        INNER JOIN instacart_{LAB_ID}.user_features uf ON uf.user_id = lt.user_id
        INNER JOIN instacart_{LAB_ID}.orders target ON target.user_id = lt.user_id
            AND target.eval_set = 'train'
        WHERE lt.order_rank = 1 -- Take last transaction in prior set
        """.format(LAB_ID=LAB_ID)
    )


def get_dataset_creation_tasks():
    sqls = [
        get_create_user_features_sql(),
        get_create_latest_transaction_sql(),
        get_create_feature_set_sql(),
    ]
    return [
        BigQueryOperator(
            task_id=name,
            sql=sql,
            use_legacy_sql=False,
        ) for name, sql in sqls
    ]


def get_tasks():
    tasks = []

    # Create a bucket
    #tasks.append(get_create_bucket_task())

    ## Copy csv files to bucket
    #tasks.append(get_copy_csv_tasks())

    ## Create a dataset
    #tasks.append(get_create_dataset_task())

    ## Copy csv to bigquery table
    #tasks.extend(get_csv_to_bigquery_tasks())

    # Run SQL to create ML data set
    tasks.extend(get_dataset_creation_tasks())

    return tasks


with models.DAG(
    'ml_pipeline',
    schedule_interval=datetime.timedelta(days=1),
    default_args=default_dag_args,
) as dag:

    tasks = get_tasks()

    # Generate dependency
    task = tasks[0]

    if len(tasks) == 1:
        task
    else:
        for i in range(1, len(tasks)):
            task >> tasks[i]
            task = tasks[i]
