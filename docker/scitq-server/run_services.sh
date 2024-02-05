#!/bin/bash
scitq-manage db upgrade-or-init
/usr/bin/supervisord -c /etc/supervisord.conf