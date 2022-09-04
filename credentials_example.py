class DbConfig(object):
  host = 'localhost'
  port = 5432
  database = 'db'
  schema = 'prod'
  user = 'postgres'
  password = 'secret'

class MinioConfig(object):
  host = 'localhost'
  bucket = 'mybucket'
  access_key = 'minio'
  secret_key = 'secret'

class RestApiConfig(object):
    url = 'https://domain/manager/v2'
    username = ''
    password = ''

db = DbConfig()
minio = MinioConfig()
