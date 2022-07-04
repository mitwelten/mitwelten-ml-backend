class NodeUploaderConfig(object):
    'Mitwelten image-uploader service configuration'

    period_start = '18:00'
    '''
    If running with --timed flag:
    Start of time period, format '%H:%M' UTC
    '''

    period_end = '06:00'
    '''
    If running with --timed flag:
    End of time period, format '%H:%M' UTC
    '''


class IndexConfig(NodeUploaderConfig):

    root_path = '/mnt/elements'
    'Directory root to index files from'

class MetaConfig(NodeUploaderConfig):

    threads = 2
    'Number of threads to spawn'

class UploadConfig(NodeUploaderConfig):

    threads = 4
    'Number of threads to spawn'


index = IndexConfig()
meta = MetaConfig()
upload = UploadConfig()
