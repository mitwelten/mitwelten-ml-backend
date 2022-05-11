class DbConfig(object):
    host = ''
    port = 5432
    database = ''
    user = ''
    password = ''

class MinioConfig(object):
    host = ''
    bucket = ''
    access_key = ''
    secret_key = ''

db = DbConfig()
minio = MinioConfig()
