import os
import json
from datetime import datetime, timedelta
import pandas as pd
from jinja2 import Environment, FileSystemLoader
import boto3

# Fetch AWS credentials from environment variables
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
aws_region = os.getenv('AWS_REGION')

if not aws_access_key_id or not aws_secret_access_key or not aws_region:
    raise EnvironmentError("AWS credentials or region not found in environment variables.")

# Initialize Cost Explorer client
client = boto3.client(
    'ce',
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=aws_region
)

# Function to get cost and usage data
def get_cost_and_usage(start_date, end_date, granularity='MONTHLY', group_by=None, filter=None):
    group_by = group_by or []
    filter = filter or {}
    
    response = client.get_cost_and_usage(
        TimePeriod={'Start': start_date, 'End': end_date},
        Granularity=granularity,
        Metrics=['UnblendedCost'],
        Filter=filter,
        GroupBy=group_by
    )
    return response

# Function to get cost forecast
def get_cost_forecast(start_date, end_date, granularity='MONTHLY', metric='UNBLENDED_COST'):
    response = client.get_cost_forecast(
        TimePeriod={'Start': start_date, 'End': end_date},
        Granularity=granularity,
        Metric=metric,
        PredictionIntervalLevel=95
    )
    return response

# Fetch historical data
end_date = datetime.today().date()
start_date = (end_date - timedelta(days=365)).strftime('%Y-%m-%d')
end_date = end_date.strftime('%Y-%m-%d')

response = get_cost_and_usage(
    start_date, end_date,
    group_by=[
        {'Type': 'DIMENSION', 'Key': 'SERVICE'},
        {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
    ],
    filter={
        "Not": {
            'Dimensions': {
                'Key': 'RECORD_TYPE',
                'Values': ['Credit', 'Refund']
            }
        }
    }
)
results = response['ResultsByTime']

# Process data to find costs for Amazon Elastic Compute Cloud - Compute
ec2_data = []
overall_data = []
services_set = set()  # To store unique services
for result in results:
    time_period = result['TimePeriod']['Start']
    for group in result['Groups']:
        service = group['Keys'][0]
        usage_type = group['Keys'][1]
        cost = float(group['Metrics']['UnblendedCost']['Amount'])
        overall_data.append([time_period, service, usage_type, cost])
        services_set.add(service)  # Add service to the set
        if service == 'Amazon Elastic Compute Cloud - Compute':
            ec2_data.append([time_period, usage_type, cost])

# Convert overall data to DataFrame
overall_df = pd.DataFrame(overall_data, columns=['TimePeriod', 'Service', 'UsageType', 'Cost'])

# Round costs to 4 decimal places
overall_df['Cost'] = overall_df['Cost'].round(2)

# Summarize costs by service and time period for overall data
overall_summary = overall_df.groupby(['TimePeriod', 'Service']).sum().reset_index()

# Calculate month-over-month comparison for overall data
overall_summary['PreviousCost'] = overall_summary.groupby('Service')['Cost'].shift(1)
overall_summary['CostChange'] = overall_summary['Cost'] - overall_summary['PreviousCost']

# Handle NaN values by replacing them with 0 for overall data
overall_summary = overall_summary.fillna(0)

# Convert overall summary to dictionary for rendering
overall_summary_dict = overall_summary.to_dict(orient='records')

# Convert services_set to a sorted list
overall_services = sorted(list(services_set))

# Fetch cost forecast for the current month
forecast_start_date = datetime.today().strftime('%Y-%m-%d')
forecast_end_date = (datetime.today().replace(day=1) + timedelta(days=32)).replace(day=1).strftime('%Y-%m-%d')

forecast_response = get_cost_forecast(forecast_start_date, forecast_end_date)
forecast_amount = float(forecast_response['Total']['Amount'])

# Get costs for Amazon Elastic Compute Cloud - Compute grouped by USAGE_TYPE and INSTANCE_TYPE
ec2_response = get_cost_and_usage(
    start_date, end_date,
    group_by=[
        {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'},
        {'Type': 'DIMENSION', 'Key': 'INSTANCE_TYPE'}
    ],
    filter={
        'Dimensions': {
            'Key': 'SERVICE',
            'Values': ['Amazon Elastic Compute Cloud - Compute']
        }
    }
)
ec2_results = ec2_response['ResultsByTime']

# Process EC2 data
data = []
for result in ec2_results:
    time_period = result['TimePeriod']['Start']
    for group in result['Groups']:
        usage_type = group['Keys'][0]
        instance_type = group['Keys'][1]
        cost = float(group['Metrics']['UnblendedCost']['Amount'])
        data.append([time_period, usage_type, instance_type, cost])

# Convert to DataFrame
df = pd.DataFrame(data, columns=['TimePeriod', 'UsageType', 'InstanceType', 'Cost'])

# Round costs to 4 decimal places
df['Cost'] = df['Cost'].round(2)

# Summarize costs by instance type and time period
summary = df.groupby(['TimePeriod', 'InstanceType']).sum().reset_index()

# Calculate month-over-month comparison
summary['PreviousCost'] = summary.groupby('InstanceType')['Cost'].shift(1)
summary['CostChange'] = summary['Cost'] - summary['PreviousCost']

# Handle NaN values by replacing them with 0
summary = summary.fillna(0)

# Calculate total cost per instance type
total_cost_per_instance = df.groupby('InstanceType')['Cost'].sum().reset_index().rename(columns={'Cost': 'TotalCost'})

# Merge total cost per instance type with summary
summary = pd.merge(summary, total_cost_per_instance, on='InstanceType', how='left')

# Convert the summary to a dictionary for rendering
summary_dict = summary.to_dict(orient='records')

# Get unique instance types for dropdown
instance_list = sorted(list(df['InstanceType'].unique()))

# Get costs for Amazon RDS grouped by INSTANCE_TYPE
rds_response = get_cost_and_usage(
    start_date, end_date,
    group_by=[
        {'Type': 'DIMENSION', 'Key': 'INSTANCE_TYPE'}
    ],
    filter={
        'Dimensions': {
            'Key': 'SERVICE',
            'Values': ['Amazon Relational Database Service']
        }
    }
)
rds_results = rds_response['ResultsByTime']

# Debug print to check RDS response
#print("RDS Response:", json.dumps(rds_results, indent=4))

# Process RDS data
rds_data = []
for result in rds_results:
    time_period = result['TimePeriod']['Start']
    for group in result['Groups']:
        instance_type = group['Keys'][0]
        cost = float(group['Metrics']['UnblendedCost']['Amount'])
        rds_data.append([time_period, instance_type, cost])

# Debug print to check RDS data
print("RDS Data:", rds_data)

# Convert to DataFrame
rds_df = pd.DataFrame(rds_data, columns=['TimePeriod', 'InstanceType', 'Cost'])

# Round costs to 4 decimal places
rds_df['Cost'] = rds_df['Cost'].round(2)

# Summarize costs by instance type and time period
rds_summary = rds_df.groupby(['TimePeriod', 'InstanceType']).sum().reset_index()

# Calculate month-over-month comparison
rds_summary['PreviousCost'] = rds_summary.groupby('InstanceType')['Cost'].shift(1)
rds_summary['CostChange'] = rds_summary['Cost'] - rds_summary['PreviousCost']

# Handle NaN values by replacing them with 0
rds_summary = rds_summary.fillna(0)

# Calculate total cost per instance type
total_cost_per_rds_instance = rds_df.groupby('InstanceType')['Cost'].sum().reset_index().rename(columns={'Cost': 'TotalCost'})

# Merge total cost per instance type with summary
rds_summary = pd.merge(rds_summary, total_cost_per_rds_instance, on='InstanceType', how='left')

# Convert the summary to a dictionary for rendering
rds_summary_dict = rds_summary.to_dict(orient='records')

# Get unique RDS instance types for dropdown
rds_instance_list = sorted(list(rds_df['InstanceType'].unique()))

# Debug print to check RDS instance list
print("RDS Instance Types:", rds_instance_list)

# Set up Jinja2 environment
env = Environment(loader=FileSystemLoader('.'))
template = env.get_template('templates/template.html')

# Get unique months for the dropdown
months = sorted(overall_summary['TimePeriod'].unique())

# Get the latest month
latest_month = months[-1]

# Map the latest month to "Current Month"
months_dict = {month: month for month in months}
months_dict[latest_month] = "Current Month"

# Render HTML
html_output = template.render(
    overall_summary=overall_summary_dict,
    ec2_summary=summary_dict,
    rds_summary=rds_summary_dict,
    months=months_dict,
    latest_month="Current Month",  # Select the latest month as "Current Month"
    instances=instance_list,
    rds_instances=rds_instance_list,
    overall_services=overall_services,
    forecast_cost=forecast_amount  # Pass the forecasted cost
)

# Write HTML to a file
with open('templates/aws_cost_report.html', 'w') as f:
    f.write(html_output)

print('HTML report generated: aws_cost_report.html')

