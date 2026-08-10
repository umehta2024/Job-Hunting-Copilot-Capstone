"""
One-time script to store the Adzuna API credentials in Databricks secrets.

Run this from a Databricks notebook to securely store your Adzuna API credentials:
    
    %sh python setup_secrets.py

Or from a notebook terminal (if enabled on your cluster):

    python setup_secrets.py

The script prompts for your Adzuna app_id, app_key, and Lakebase URL and stores them 
as base64-encoded secrets in the `job_hunting` scope. The job hunting app reads from 
these secrets.
"""

import base64
import getpass

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

SCOPE = "job_hunting"
APP_ID_KEY = "app_id"
APP_KEY_KEY = "app_key"
LAKEBASE_URL_KEY = "lakebase_url"


def ensure_scope(scope: str):
    """Create the secret scope if it doesn't exist."""
    try:
        w.secrets.create_scope(scope=scope)
        print(f"✅ Created secret scope: {scope}")
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"✅ Secret scope already exists: {scope}")
        else:
            raise


def store_secret(scope: str, key: str, value: str):
    """Store a secret value (base64 encoded)."""
    encoded_value = base64.b64encode(value.encode()).decode()
    w.secrets.put_secret(scope=scope, key=key, string_value=encoded_value)
    print(f"✅ Stored secret: {scope}/{key}")


def main():
    print("=" * 70)
    print("Job Hunting Copilot - Adzuna API Secret Setup")
    print("=" * 70)
    print()
    print("This script stores your Adzuna API credentials and Lakebase URL as Databricks secrets.")
    print("You will need:")
    print()
    print("  1. app_id  - Your Adzuna application ID")
    print("  2. app_key - Your Adzuna application key")
    print("  3. lakebase_url - Your Lakebase Postgres connection URL")
    print()
    print("Adzuna API is used to fetch job listings from:")
    print("  https://api.adzuna.com/v1/api/jobs/gb/search/1?app_id={YOUR_APP_ID}&app_key={YOUR_APP_KEY}")
    print()
    print("Lakebase URL should look like:")
    print("  postgresql://role:password@host.cloud.databricks.com:5432/databricks_postgres?sslmode=require")
    print()
    print("Get your Adzuna credentials at: https://developer.adzuna.com/")
    print()
    
    # Ensure the scope exists
    ensure_scope(SCOPE)
    print()
    
    # Prompt for app_id
    print("Please enter your Adzuna app_id:")
    print("(Input is hidden for security)")
    app_id = getpass.getpass("App ID: ").strip()
    
    if not app_id:
        print("❌ No app_id provided. Exiting.")
        return
    
    # Prompt for app_key
    print()
    print("Please enter your Adzuna app_key:")
    print("(Input is hidden for security)")
    app_key = getpass.getpass("App Key: ").strip()
    
    if not app_key:
        print("❌ No app_key provided. Exiting.")
        return
    
    # Prompt for Lakebase URL
    print()
    print("Please enter your Lakebase connection URL:")
    print("(Input is hidden for security)")
    lakebase_url = getpass.getpass("Lakebase URL: ").strip()
    
    if not lakebase_url:
        print("❌ No Lakebase URL provided. Exiting.")
        return
    
    if not lakebase_url.startswith("postgresql://"):
        print("⚠️  Warning: URL should start with 'postgresql://'")
        confirm = input("Continue anyway? (y/n): ").strip().lower()
        if confirm != "y":
            print("❌ Cancelled.")
            return
    
    # Store all secrets
    store_secret(SCOPE, APP_ID_KEY, app_id)
    store_secret(SCOPE, APP_KEY_KEY, app_key)
    store_secret(SCOPE, LAKEBASE_URL_KEY, lakebase_url)
    
    print()
    print("=" * 70)
    print("✅ Setup complete!")
    print("=" * 70)
    print()
    print("Your Adzuna API credentials and Lakebase URL are now stored securely.")
    print()
    print("Next steps:")
    print("  1. Deploy the Job Hunting Copilot app (it will use these secrets)")
    print("  2. Test the API connection")
    print("  3. Start searching for jobs!")
    print()


if __name__ == "__main__":
    main()
