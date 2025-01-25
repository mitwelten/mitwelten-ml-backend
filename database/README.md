# Database Setup (retired)

In a first step, the database schema was laid out based on the existing data,
starting with audio files recorded by audiomoths. This produced the schema
documented in [schema v1](./schema_v1.pgerd),
as defined in [initialize_db.sql](./initialize_db.sql).

While this serves well as base for prototypes, a __schema v2__ aims to unify
the table structure to reflect all data for the project. It is managed in a
[separate GitHub repository](https://github.com/mitwelten/mitwelten-db-backend).

## Tables

| table | description |
| - | - |
| configs | BirdNET configuration referred to by the task queue |
| files | audio files metadata, facilitating import process of existing data |
| files_image | image files metadata, pollinators |
| results | BirdNET inference results |
| species_occurrence | hand crafted table of species to be observed at merian gardens |
| tasks | Task queue for BirdNET inference job runenr |
