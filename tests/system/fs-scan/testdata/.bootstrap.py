# hidden bootstrap script run by container entrypoint
import os
os.environ.setdefault('APP_ENV', 'development')
