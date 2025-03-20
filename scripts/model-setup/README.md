# Deploy model in RHOAI


## Prerequisites

Before you can serve a model in Red Hat OpenShift AI, you will need to install RHOAI and enable NVIDIA GPU by following these links:
* [Red Hat OpenShift AI installation](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/2.13/html-single/installing_and_uninstalling_openshift_ai_self-managed/index#installing-and-deploying-openshift-ai_install)
* [Enable NVIDIA GPU](https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/2.13/html/installing_and_uninstalling_openshift_ai_self-managed/enabling-nvidia-gpus_install#enabling-nvidia-gpus_install)

This project uses `MinIO` to store the model:
  * _Install the `oc` client to use MinIO for model storage_


## Quickstart

Open up `Red Hat OpenShift AI` by selecting it from OpenShift Application Launcher. This will open up Red Hat OpenShift AI in a new tab.

Create a Data Science project in `Red Hat OpenShift AI` window.

### Setup MinIO
To setup MinIO, for storing the model, execute the following commands in a terminal/console:
```
# Login to OpenShift (if not already logged in)
oc login --token=<OCP_TOKEN>

# Install MinIO
MINIO_USER=<USERNAME> \
   MINIO_PASSWORD="<PASSWORD>" \
   envsubst < minio-setup.yml | \
   oc apply -f - -n <DATA_SCIENCE_PROJECT_CREATED_IN_PREVIOUS_STEP>
```
* _Set `<USERNAME>` and `<PASSWORD>` to some valid values, in the above command, before executing it_

Once MinIO is setup, you can access it within your project. The yaml that was applied above creates these two routes:
* `minio-ui` - for accessing the MinIO UI
* `minio-api` - for API access to MinIO
  * Take note of the `minio-api` route location as that will be needed in next section.


### Create Data connection
Create a new data connection that can be used by the init-container (`storage-initializer`) to fetch the model uploaded in next step when deploying the model.

To create a Data connection, use the following steps:
* Click on `Add data connection` button in the  `Data connections` tab in your newly created project
* Use the following values for this data connection:
  * _Name_: `minio`
  * _Access key_: value specified for `AWS_ACCESS_KEY_ID` field in `Create Workbench` section
  * _Secret key_: value specified for `AWS_SECRET_ACCESS_KEY` field in `Create Workbench` section
  * _Endpoint_: value specified for `AWS_S3_ENDPOINT` field in `Create Workbench` section
  * _Access key_: value specified for `AWS_DEFAULT_REGION` field in `Create Workbench` section
  * _Bucket_: value specified for `AWS_S3_BUCKET` field in `Create Workbench` section
* Create the data connection by clicking on `Add data connection` button


### Create workbench
To use RHOAI for this project, you need to create a workbench first. In the newly created data science project, create a new Workbench by clicking `Create workbench` button in the `Workbenches` tab.

Use the following values:
* _Notebook image_:
  * Image selection: **PyTorch**
  * Version selection: **2024.1**
* _Deployment size_:
  * Container size: **Medium**
  * Accelerator: **NVIDIA GPU**
  * Number of accelerators: **1**
* _Cluster storage_: **50GB**
* Connections: Click on `Attach existing connections` button and **Attach** the Data Connection created in previous step. This will pass on the data connection values to the RHOAI workbench when it is started.

Create the workbench with above settings.


### Open workbench
Open the newly created workbench by following these steps:
* Select your newly created project by clicking on `Data Science Projects` in the sidebar menu
* Click on `Workbenches` tab and open the newly created workbench by clicking on the `Open` link
* The workbench will open up in a new tab
* _When the workbench is opened for the first time, you will be shown an `Authorize Access` page._
  * _Click `Allow selected permissions` button in this page._


### Clone repo
Now that the workbench is created and running, follow these steps to setup the project:
* In the workbench, click on `Terminal` icon in the `Launcher` tab.
* Clone this repository in the `Terminal` by running the following command:
  `git clone https://github.com/sgahlot/qna-chat-amd.git`


### Run Jupyter notebook
_The notebook mentioned in this section is used to download the `meta-llama/Llama-3.1-8B-Instruct` model and upload it to MinIO_

* Once the repository is cloned, select the folder where you cloned the repository (in the sidebar) and navigate to `scripts/model-setup` directory and open up [download-n-upload-model-to-minio.ipynb](./download-n-upload-model-to-minio.ipynb)
* Run this notebook by selecting `Run` -> `Run All Cells` menu item
* _When the notebook successfully runs, llama model should have been uploaded to MinIO under `<AWS_S3_BUCKET>/Llama-3.1-8B-Instruct` directory_.


### Deploy model
Once the initial notebook has run successfully and the data connection is created, you can deploy the model by following these steps:
* In the RHOAI tab, select `Models` tab (_for your newly created project_) and click on `Deploy model` button 
* Fill in the following fields as described below:
  * _Model name_: **<PROVIDE_a_name_for_the_model>**
  * _Serving runtime_: `vLLM ServingRuntime for KServe`
  * _Model framework_: **vLLM**
  * _Model server size_: **Small**
  * _Accelerator_: **NVIDIA GPU**
  * _Model route_:
    * _If you want to access this model endpoint from outside the cluster_, make sure to check the `Make deployed models available through an external route` checkbox. By default, the model endpoint is only available as an _internal service_.
  * _Model location_: Select **Existing data connection** option
    * _Name_: **Name of data connection created in previous step**
    * _Path_: **Llama-3.1-8B-Instruct**
      * _This is where the model was copied to in `download-n-upload-model-to-minio` notebook._
* In `Additional serving runtime arguments` (under Configuration parameters), provide the following:
  * `--max_model_len=4096`
* Click on `Deploy` to deploy this model

Copy the `inference endpoint` once the model is deployed successfully (_it will take a few minutes to deploy the model_).
