class DbConfig(object):
  host = 'localhost'
  port = 5432
  database = 'db'
  schema = 'public'
  user = 'postgres'
  password = 'secret'

class MinioConfig(object):
  host = 'localhost'
  bucket = 'mybucket'
  access_key = 'minio'
  secret_key = 'secret'

db = DbConfig()
minio = MinioConfig()
