#!/bin/bash
curl -sf http://localhost:${SERVER_PORT:-3002}/health || exit 1
