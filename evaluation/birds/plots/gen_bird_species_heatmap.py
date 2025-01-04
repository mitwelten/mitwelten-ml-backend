import csv
import numpy as np
import matplotlib.pyplot as plt
import psycopg2 as pg
import credentials as crd

locations = {
    'park' : {
        'deployment_id': 6,
        'label': '3704-8490',
        'species': [
            'Turdus merula',
            'Fringilla coelebs',
            'Certhia brachydactyla',
            'Motacilla cinerea',
            'Muscicapa striata',
            'Picus viridis',
            'Parus major',
            'Cuculus canorus',
            'Apus apus',
            'Sylvia atricapilla',
            'Alopochen aegyptiaca',
            'Columba palumbus',
            'Erithacus rubecula',
            'Turdus philomelos',
            'Carduelis carduelis',
        ]
    },
    'pasture' : {
        'deployment_id': 3,
        'label': '2061-6644',
        'species': [
            'Turdus merula',
            'Passer montanus',
            'Motacilla cinerea',
            'Muscicapa striata',
            'Phoenicurus ochruros',
            'Passer domesticus',
            'Apus apus',
            'Delichon urbicum',
            'Turdus viscivorus',
            'Columba palumbus',
            'Milvus milvus',
            'Sturnus vulgaris',
            'Carduelis carduelis',
            'Falco tinnunculus',
            'Ciconia ciconia',
        ]
    },
    'garden' : {
        'deployment_id': 4,
        'label': '1874-8542',
        'species': [
            'Turdus merula',
            'Certhia brachydactyla',
            'Motacilla cinerea',
            'Serinus serinus',
            'Picus viridis',
            'Phoenicurus ochruros',
            'Passer domesticus',
            'Parus major',
            'Apus apus',
            'Delichon urbicum',
            'Columba palumbus',
            'Aegithalos caudatus',
            'Falco tinnunculus',
            'Strix aluco',
            'Ciconia ciconia'
        ]
    },
    'meadow' : {
        'deployment_id': 5,
        'label': '4672-2602',
        'species': [
            'Turdus merula',
            'Cyanistes caeruleus',
            'Certhia brachydactyla',
            'Motacilla cinerea',
            'Serinus serinus',
            'Muscicapa striata',
            'Picus viridis',
            'Phoenicurus ochruros',
            'Apus apus',
            'Columba palumbus',
            'Aegithalos caudatus',
            'Sturnus vulgaris',
            'Carduelis carduelis',
            'Troglodytes troglodytes',
            'Phylloscopus collybita',
        ]
    },
    'pond' : {
        'deployment_id': 7,
        'label': '4258-6870',
        'species': [
            'Turdus merula',
            'Fringilla coelebs',
            'Motacilla cinerea',
            'Serinus serinus',
            'Muscicapa striata',
            'Chloris chloris',
            'Apus apus',
            'Sylvia atricapilla',
            'Columba palumbus',
            'Erithacus rubecula',
            'Aegithalos caudatus',
            'Carduelis carduelis',
            'Gallinula chloropus',
            'Acrocephalus scirpaceus',
            'Troglodytes troglodytes'
        ]
    }
}

with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
    with conn.cursor() as cur:
        stats_location = {}
        for l, details in locations.items():
            # # use with incomplete days filter below
            # if details['label'] != '2061-6644':
            #     continue
            query = f'''
            select species, extract('hour' from f.time) as hour, count(*) from prod.birdnet_results r
            left join prod.files_audio f on f.file_id = r.file_id
            -- -- this is an attempt to filter out the incomplete days for the park location
            -- where (
            --     f.time between '2021-05-10 17:00:00' and '2021-06-17 17:00:00'
            --     or f.time between '2021-05-20 00:00:00' and '2021-05-21 00:00:00'
            --     or f.time between '2021-05-28 17:00:00' and '2021-06-09 17:00:00'
            --     or f.time between '2021-06-12 19:00:00' and '2021-06-23 19:00:00'
            -- )
            where f.time between '2021-05-09 00:00:00' and '2021-06-25 00:00:00'
            and f.deployment_id = {details['deployment_id']} and
            confidence > 0.7 and
            species in ({', '.join([f"'{s}'" for s in details['species']])})
            group by species, hour;
            '''
            cur.execute(query)
            data = cur.fetchall()
            stats_location[l] = [(r[0], int(r[1]), int(r[2]))for r in data]


# # read data from csv
# csv_file = open('birds-heatmap.csv', 'r')
# csv_reader = csv.reader(csv_file, delimiter=';')
# data = []
# next(csv_reader) # skip header
# for row in csv_reader:
#     data.append([row[0], int(row[1]), int(row[2])])

# get max count
max_count = max([max([c[2] for c in row]) for row in stats_location.values()])

for location, data in stats_location.items():
    # create heatmap
    heatmap = {}
    for row in data:
        if row[0] not in heatmap:
            heatmap[row[0]] = {}
        heatmap[row[0]][row[1]] = row[2]

    # create heatmap plot
    species = list(heatmap.keys())

    # hours = sorted(list(set([row[1] for row in data])))
    hours = range(24)
    counts = np.zeros((len(species), len(hours)))
    for i, specie in enumerate(species):
        for j, hour in enumerate(hours):
            counts[i][j] = heatmap[specie].get(hour, 0)
    plt.clf()
    plt.figure(figsize=(16, 7))
    # plt.subplots_adjust(left=0.2)  # adjust the left margin
    plt.imshow(counts, cmap='Spectral', interpolation='nearest', aspect='auto')
    plt.xticks(range(len(hours)), hours)
    plt.yticks(range(len(species)), species)
    plt.clim(0, max_count) # set the range of the colorbar
    plt.colorbar(label='Count')
    plt.xlabel('Hour (UTC)')
    plt.ylabel('Species')
    plt.title(f'Bird Species Heatmap ({location}, {locations[location]["label"]}, 2021-05-09 - 2021-06-24)')
    plt.tight_layout(pad=2)
    plt.savefig(f'birds-heatmap_{location}.png', dpi=300) # bbox_inches='tight'
