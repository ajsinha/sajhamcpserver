#!/usr/bin/env python3
"""
SAJHA MCP Server v4.0.0 — AWS CDK App
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Deploy:
    cd aws/cdk
    pip install -r requirements.txt
    cdk bootstrap        # first time only
    cdk deploy           # deploy stack
    cdk destroy          # tear down
"""
import aws_cdk as cdk
from sajha_stack import SajhaStack

app = cdk.App()

SajhaStack(app, "sajha-mcp-server",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
    # Override defaults via context:
    #   cdk deploy -c environment=prod -c cpu=1024 -c memory=2048
)

app.synth()
