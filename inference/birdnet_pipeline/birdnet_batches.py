import sys
sys.path.append('../../')
import credentials as crd

SCHEMA = crd.db.schema

batches = {}
'''BirdNET: batches of files, usually grouped by node label'''

# BATCH_ID 0 ('test')
batches[0] = {
'comment': 'testing batch',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input
where duration >= 3 and
    node_label = '4242-2323'
order by time asc
'''}

# BATCH_ID 1
batches[1] = {
'comment': 'FS1 nodes AM1 and AM2',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input
where duration >= 3 and sample_rate = 48000 and
    node_label ~ 'AM[12]'
order by time asc
'''}

# BATCH_ID 2
batches[2] = {
'comment': 'FS1 node 6444-8804',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input
where duration >= 3 and sample_rate = 48000 and
    node_label = '6444-8804'
order by time asc
'''}

# BATCH_ID 3
batches[3] = {
'comment': 'FS1 node 4258-6870',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input
where duration >= 3 and sample_rate = 48000 and
    node_label = '4258-6870'
order by time asc
'''}

# BATCH_ID 4
batches[4] = {
'comment': 'FS1 node 3704-8490',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input
where duration >= 3 and sample_rate = 48000 and
    node_label = '3704-8490'
order by time asc
'''}

# BATCH_ID 5
# a.k.a. the ultimate birdnet query
# all files that:
# - don't show up in results
# - sampling rate == 48kHz
# - duration >= 3s
# - filesize < 1100MB

batches[5] = {
'comment': 'All files that don\'t show up in results',
'query': f'''
select file_id, object_name,
    floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from {SCHEMA}.birdnet_input i
where sample_rate = 48000 and duration >= 3 and not exists (
    select from {SCHEMA}.birdnet_results o where i.object_name = o.object_name
)
'''}

batches[7] = {
'comment': 'FS2: 8367-2852',
'query': f'''
select file_id, object_name,
floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from dev.birdnet_input i
where time > '2022-03-01 00:00:00+02' and sample_rate = 48000 and duration >= 3 and node_label = '8367-2852'
'''}

batches[8] = {
'comment': 'FS2: 8537-4761',
'query': f'''
select file_id, object_name,
floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from dev.birdnet_input i
where time > '2022-03-01 00:00:00+02' and sample_rate = 48000 and duration >= 3 and node_label = '8537-4761'
'''}

batches[9] = {
'comment': 'FS2: 8542-0446',
'query': f'''
select file_id, object_name,
floor((extract(doy from time) - 1)/(365/48.))::integer + 1 as week
from dev.birdnet_input i
where time > '2022-03-01 00:00:00+02' and sample_rate = 48000 and duration >= 3 and node_label = '8542-0446'
'''}
