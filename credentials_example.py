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

class OidcConfig(object):
    KC_SERVER_URL = 'https://identityprovider.tld/auth/'
    KC_CLIENT_ID = 'client_id'
    KC_REALM_NAME = 'realm'
    KC_CLIENT_SECRET = 'secret'

db = DbConfig()
minio = MinioConfig()
api = RestApiConfig()
oidc = OidcConfig()
