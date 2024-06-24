SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 1243 -- 8367-2852 (ID 1243, Velodach, Gebüsch) 2023-05-11 - 2023-10-02
  AND r.species in (
    'Cuculus canorus',
    'Dryocopus martius',
    'Coccothraustes coccothraustes',
    'Fulica atra',
    'Muscicapa striata',
    'Asio otus',
    'Gallinula chloropus',
    'Turdus pilaris'
  )
UNION
SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 1261 -- 8537-4761 (Id 1261, Kims Wagon) 2023-05-03 - 2023-10-01
  AND r.species in (
    'Strix aluco',
    'Anthus trivialis',
    'Anthus pratensis',
    'Asio otus',
    'Chroicocephalus ridibundus',
    'Ficedula hypoleuca',
    'Fulica atra'
  )
UNION
SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 541 -- 6174-3985 (ID 541, Wald) 2023-03-27 - 2023-08-30
  AND r.species in (
    'Coccothraustes coccothraustes',
    'Dendrocoptes medius',
    'Luscinia megarhynchos',
    'Oriolus oriolus',
    'Dryocopus martius',
    'Turdus iliacus',
    'Anthus trivialis',
    'Corvus frugilegus',
    'Oenanthe oenanthe',
    'Phylloscopus sibilatrix',
    'Sylvia borin',
    'Tachybaptus ruficollis'
  )
UNION
SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 679 -- 7025-1446 (ID 679, Birs) 2023-03-27 - 2023-09-26
  AND r.species in (
    'Cygnus olor',
    'Tringa ochropus',
    'Actitis hypoleucos',
    'Anthus trivialis',
    'Sylvia borin',
    'Curruca curruca',
    'Phoenicurus phoenicurus',
    'Tringa erythropus',
    'Cuculus canorus',
    'Curruca communis',
    'Jynx torquilla',
    'Merops apiaster',
    'Phylloscopus sibilatrix'
  )
UNION
SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 616 -- 5950-1820 (ID 616, Wiese) 2023-03-27 - 2023-09-22
  AND r.species in (
    'Ciconia Ciconia',
    'Jynx torquilla',
    'Curruca curruca',
    'Muscicapa striata',
    'Turdus iliacus',
    'Anthus trivialis',
    'Phoenicurus phoenicurus'
  )
UNION
SELECT f.object_name, f.file_id, r.result_id, f.duration, r.species, r.time_start, r.time_end, r.confidence
FROM prod.birdnet_results r
JOIN prod.files_audio f ON r.file_id = f.file_id
JOIN prod.birdnet_tasks t ON r.task_id = t.task_id
WHERE t.config_id = 1 and r.confidence >= 0.4
  AND "time" between '2023-05-11 00:00:00' and '2023-06-27 00:00:00'
  AND f.deployment_id = 503 -- 8542-0446 (ID 503, ErlebnisWeiher) 2023-03-27 - 2023-08-30
  AND r.species in (
    'Podiceps grisegena',
    'Tringa ochropus',
    'Merops apiaster',
    'Oenanthe oenanthe',
    'Curruca curruca',
    'Turdus iliacus',
    'Apus melba',
    'Asio otus',
    'Saxicola rubicola'
  )
;
