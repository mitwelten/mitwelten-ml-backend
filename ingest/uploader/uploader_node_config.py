class NodeUploaderConfig(object):
    'Mitwelten image-uploader service configuration'

    period_start = '19:00'
    '''
    If running with --timed flag:
    Start of time period, format '%H:%M' (system time)
    '''

    period_end = '07:00'
    '''
    If running with --timed flag:
    End of time period, format '%H:%M' (system time)
    '''


class IndexConfig(NodeUploaderConfig):

    root_path = '/mnt/elements'
    'Directory root to index files from'

class MetaConfig(NodeUploaderConfig):

    threads = 1
    'Number of threads to spawn'

class UploadConfig(NodeUploaderConfig):

    period_start = '15:15'
    period_end = '08:45'
    threads = 2
    'Number of threads to spawn'


index = IndexConfig()
meta = MetaConfig()
upload = UploadConfig()
