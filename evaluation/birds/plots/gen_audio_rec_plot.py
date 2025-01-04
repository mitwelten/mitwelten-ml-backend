'''
# data format

| node_label | date                 | file_name                                                  | duration |
| ---------- | -------------------- | ---------------------------------------------------------- | -------- |
| 2061-6644  | 2021-05-10T12-48-53Z | 2061-6644/2021-05-10/12/2061-6644_2021-05-10T12-48-53Z.wav | 2        |
| 1874-8542  | 2021-05-10T12-50-00Z | 1874-8542/2021-05-10/12/1874-8542_2021-05-10T12-50-00Z.wav | 0.33625  |
| 1874-8542  | 2021-05-10T12-50-23Z | 1874-8542/2021-05-10/12/1874-8542_2021-05-10T12-50-23Z.wav | 2.04291  |
| 4672-2602  | 2021-05-10T12-51-10Z | 4672-2602/2021-05-10/12/4672-2602_2021-05-10T12-51-10Z.wav | 3.06691  |
| 3704-8490  | 2021-05-10T12-55-10Z | 3704-8490/2021-05-10/12/3704-8490_2021-05-10T12-55-10Z.wav | 45       |
| 3704-8490  | 2021-05-10T12-56-00Z | 3704-8490/2021-05-10/12/3704-8490_2021-05-10T12-56-00Z.wav | 55       |
| 3704-8490  | 2021-05-10T12-57-00Z | 3704-8490/2021-05-10/12/3704-8490_2021-05-10T12-57-00Z.wav | 55       |
| 3704-8490  | 2021-05-10T12-58-00Z | 3704-8490/2021-05-10/12/3704-8490_2021-05-10T12-58-00Z.wav | 55       |
| 3704-8490  | 2021-05-10T12-59-00Z | 3704-8490/2021-05-10/12/3704-8490_2021-05-10T12-59-00Z.wav | 55       |

'''

from matplotlib import pyplot as plt
import numpy as np
import psycopg2 as pg
import credentials as crd
from datetime import datetime

# from gen_bird_species_heatmap import locations

# # compile node info from locations
# node_info = {}
# for location in locations:
#     node_info[locations[location]['label']] = {
#         'label': locations[location]['label'],
#         'location': location,
#         'deployment_id': locations[location]['deployment_id'],
#         'species': locations[location]['species']
#     }

with pg.connect(host=crd.db.host, port=crd.db.port, database=crd.db.database, user=crd.db.user, password=crd.db.password) as conn:
    with conn.cursor() as cur:
        cur.execute('''
        select
            n.node_label,
            f.time as date,
            f.object_name as object_name,
            f.duration
        from prod.files_audio f
        join prod.deployments d on d.deployment_id = f.deployment_id
        join prod.nodes n on n.node_id = d.node_id
        -- where time between '2021-05-08 00:00:00' and '2021-06-26 00:00:00'
        --             and sample_rate = 48000
        where time between '2023-03-27 00:00:00' and '2023-09-29 00:00:00'
                    and sample_rate = 250000
        order by time asc;
        ''')
        data = cur.fetchall()

        cur.execute('''
        select
            n.node_label,   -- 0
            period,         -- 1
            location,       -- 2
            d.description,  -- 3
            d.deployment_id -- 4
        from prod.deployments d
        left join prod.nodes n on n.node_id = d.node_id
        left join prod.mm_tags_deployments mm on mm.deployments_deployment_id = d.deployment_id
        left join prod.tags t on t.tag_id = mm.tags_tag_id
        where d.deployment_id in (575,649,715,1771,1777,2816)
        ;
        ''')
        deployements = cur.fetchall()

# for bats
node_info = {}
for d in deployements:
    if d[0] not in node_info:
        node_info[d[0]] = {
            'label': d[0],
        'location': d[3],
        'deployment_id': d[4]
    }

unique_node_labels = np.unique([record[0] for record in data])
start_date = datetime.strptime('2023-03-26', '%Y-%m-%d').date()
end_date = datetime.strptime('2023-09-29', '%Y-%m-%d').date()

for node_label in unique_node_labels:
    # extract the relevant columns
    times = [record[1].hour * 3600 + record[1].minute * 60 + record[1].second for record in data if record[0] == node_label]
    dates = [record[1].date() for record in data if record[0] == node_label]
    plt.clf()
    plt.figure(figsize=(10, 6))
    plt.scatter(dates, times, alpha=0.1, color='green')
    plt.xlabel('Date')
    if node_label in node_info:
        plt.title(f'Recording times for Node {node_label} ({node_info[node_label]["location"]})')
    else:
        plt.title(f'Recording times for Node {node_label}')
    plt.xticks(rotation=90)
    plt.gca().set_xlim([start_date, end_date])
    plt.gca().xaxis.set_major_locator(plt.MultipleLocator(7))  # set the x-axis tick frequency to every 7 days
    plt.yticks(np.arange(0, 24*3600, 3600), np.arange(0, 24, 1))
    plt.ylabel('Time of day (h)')
    plt.tight_layout()
    plt.savefig(f'{node_label}_recording_times.png', dpi=300)
