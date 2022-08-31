class DbConfig(object):
    host = ''
    port = 5432
    database = ''
    schema = 'prod'
    user = ''
    password = ''

class MinioConfig(object):
    host = ''
    bucket = ''
    access_key = ''
    secret_key = ''

class RestApiConfig(object):
    url = 'https://domain/manager/v2'
    username = ''
    password = ''

db = DbConfig()
minio = MinioConfig()
