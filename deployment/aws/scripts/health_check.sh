#!/bin/bash
# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
curl -sf http://localhost:${SERVER_PORT:-3002}/health || exit 1
