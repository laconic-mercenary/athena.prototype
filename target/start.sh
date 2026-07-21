#!/bin/bash
set -e

service ssh start
exec apache2ctl -D FOREGROUND
