# Evaluation of BirdNET Model

We did not user label-studio to generate ground truth for training our models,
the labeling process predated the use of label-studio in our workflow.

We use label-studio to evaluate the performance of our models. For this purpose,
we created a labeling template that displays the predictions of the model and
allows the user to correct / evaluate them:

[label_config.xml](./label-studio/label_config.xml)

Another labeling template was created to demonstrate the use of a predefined
taxonomy for manually labeling audio files:

[label_config_taxonomy.xml](./label-studio/label_config_taxonomy.xml)
