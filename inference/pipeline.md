# Pipeline

## parts

- define configurations
- define tasks
- run tasks

## configurations

- species list
- overlap
- random
- result type
- model version

### species list

one of `auto` | `db` | `file`

#### auto

- latitude (47.53774126535403)
- longitude (7.613764385606163)
- season
  - year
  - take from `time_start`
- locaction filter threshold

#### db

- selection criteria

#### file

- filename

### overlap

- overlap $[0, 3)$

### random

- seed (42)
- gain (0.3)

### result type

- rtype (audacity)

### model version

2.1
