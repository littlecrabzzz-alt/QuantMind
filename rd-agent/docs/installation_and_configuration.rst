==============================
Installation and Configuration
==============================

Installation
============

**Install RDAgent**: For different scenarios

- for purely users: please use ``pip install rdagent`` to install RDAgent
- for upstream contributors: `Upstream development guide <https://github.com/microsoft/RD-Agent/blob/main/docs/development.rst>`_. QuantMind maintainers should use the host repository's environment and integration entry points instead.

**Install Docker**: RDAgent is designed for research and development, acting like a human researcher and developer. It can write and run code in various environments, primarily using Docker for code execution. This keeps the remaining dependencies simple. Users must ensure Docker is installed before attempting most scenarios. Please refer to the `official 🐳Docker page <https://docs.docker.com/engine/install/>`_ for installation instructions.
Ensure the current user can run Docker commands **without using sudo**. You can verify this by executing `docker run hello-world`.

LiteLLM Backend Configuration (Default)
=======================================

.. note::
   🔥 **Attention**: We now provide experimental support for **DeepSeek** models! You can use DeepSeek's official API for cost-effective and high-performance inference. See the configuration example below for DeepSeek setup.

Option 1: Unified API base for both models
------------------------------------------

   .. code-block:: Properties

      # Set to any model supported by LiteLLM.
      CHAT_MODEL=gpt-4o 
      EMBEDDING_MODEL=text-embedding-3-small
      # Configure unified API base
      # The backend api_key fully follows the convention of litellm.
      OPENAI_API_BASE=<your_unified_api_base>
      OPENAI_API_KEY=<replace_with_your_openai_api_key>

Option 2: Separate API bases for Chat and Embedding models
----------------------------------------------------------

   .. code-block:: Properties

      # Set to any model supported by LiteLLM.
      
      # CHAT MODEL:
      CHAT_MODEL=gpt-4o 
      OPENAI_API_BASE=<your_chat_api_base>
      OPENAI_API_KEY=<replace_with_your_openai_api_key>

      # EMBEDDING MODEL:
      # TAKE siliconflow as an example, you can use other providers.
      # Note: embedding requires litellm_proxy prefix
      EMBEDDING_MODEL=litellm_proxy/BAAI/bge-large-en-v1.5
      LITELLM_PROXY_API_KEY=<replace_with_your_siliconflow_api_key>
      LITELLM_PROXY_API_BASE=https://api.siliconflow.cn/v1

Configuration Example: DeepSeek Setup
-------------------------------------

Many users encounter configuration errors when setting up DeepSeek. Here's a complete working example:

   .. code-block:: Properties

      # CHAT MODEL: Using DeepSeek Official API
      CHAT_MODEL=deepseek/deepseek-chat 
      DEEPSEEK_API_KEY=<replace_with_your_deepseek_api_key>

      # EMBEDDING MODEL: Using SiliconFlow for embedding since DeepSeek has no embedding model.
      # Note: embedding requires litellm_proxy prefix
      EMBEDDING_MODEL=litellm_proxy/BAAI/bge-m3
      LITELLM_PROXY_API_KEY=<replace_with_your_siliconflow_api_key>
      LITELLM_PROXY_API_BASE=https://api.siliconflow.cn/v1

Necessary parameters include:

- `CHAT_MODEL`: The model name of the chat model.

- `EMBEDDING_MODEL`: The model name of the embedding model.

- `OPENAI_API_BASE`: The base URL of the API. If `EMBEDDING_MODEL` does not start with `litellm_proxy/`, this is used for both chat and embedding models; otherwise, it is used for `CHAT_MODEL` only.

Optional parameters (required if your embedding model is provided by a different provider than `CHAT_MODEL`):

- `LITELLM_PROXY_API_KEY`: The API key for the embedding model, required if `EMBEDDING_MODEL` starts with `litellm_proxy/`.

- `LITELLM_PROXY_API_BASE`: The base URL for the embedding model, required if `EMBEDDING_MODEL` starts with `litellm_proxy/`.

**Note:** If you are using an embedding model from a provider different from the chat model, remember to add the `litellm_proxy/` prefix to the `EMBEDDING_MODEL` name.


The `CHAT_MODEL` and `EMBEDDING_MODEL` parameters will be passed into LiteLLM's completion function. 

Therefore, when utilizing models provided by different providers, first review the interface configuration of LiteLLM. The model names must match those allowed by LiteLLM.

Additionally, you need to set up the the additional parameters for the respective model provider, and the parameter names must align with those required by LiteLLM.

For example, if you are using a DeepSeek model, you need to set as follows:

   .. code-block:: Properties

      # For some models LiteLLM requires a prefix to the model name.
      CHAT_MODEL=deepseek/deepseek-chat
      DEEPSEEK_API_KEY=<replace_with_your_deepseek_api_key>

Besides, when you are using reasoning models, the response might include the thought process. For this case, you need to set the following environment variable:
   
   .. code-block:: Properties
      
      REASONING_THINK_RM=True

For more details on LiteLLM requirements, refer to the `official LiteLLM documentation <https://docs.litellm.ai/docs>`_.

Configuration Example 2: Azure OpenAI Setup
-------------------------------------------
Here’s a sample configuration specifically for Azure OpenAI, based on the `official LiteLLM documentation <https://docs.litellm.ai/docs>`_:

If you're using Azure OpenAI, below is a working example using the Python SDK, following the `LiteLLM Azure OpenAI documentation <https://docs.litellm.ai/docs/providers/azure/>`_:

   .. code-block:: Properties

      from litellm import completion
      import os
      
      # Set Azure OpenAI environment variables
      os.environ["AZURE_API_KEY"] = "<your_azure_api_key>"
      os.environ["AZURE_API_BASE"] = "<your_azure_api_base>"
      os.environ["AZURE_API_VERSION"] = "<version>"
      
      # Make a request to your Azure deployment
      response = completion(
        "azure/<your_deployment_name>",
        messages = [{ "content": "Hello, how are you?", "role": "user" }]
      )

To align with the Python SDK example above, you can configure the `CHAT_MODEL` based on the `response` model setting and use the corresponding `os.environ` variables by writing them into your local `.env` file as follows:

   .. code-block:: Properties

      cat << EOF > .env
      # CHAT MODEL: Azure OpenAI via LiteLLM
      CHAT_MODEL=azure/<your_deployment_name>
      AZURE_API_BASE=https://<your_azure_base>.openai.azure.com/
      AZURE_API_KEY=<your_azure_api_key>
      AZURE_API_VERSION=<version>
      
      # EMBEDDING MODEL: Using SiliconFlow via litellm_proxy
      EMBEDDING_MODEL=litellm_proxy/BAAI/bge-large-en-v1.5
      LITELLM_PROXY_API_KEY=<your_siliconflow_api_key>
      LITELLM_PROXY_API_BASE=https://api.siliconflow.cn/v1
      EOF

This configuration allows you to call Azure OpenAI through LiteLLM while using an external provider (e.g., SiliconFlow) for embeddings.

If your `Azure OpenAI API Key`` supports `embedding model`, you can refer to the following configuration example.

   .. code-block:: Properties

      cat << EOF  > .env
      EMBEDDING_MODEL=azure/<Model deployment supporting embedding>
      CHAT_MODEL=azure/<your deployment name>
      AZURE_API_KEY=<replace_with_your_openai_api_key>
      AZURE_API_BASE=<your_unified_api_base>
      AZURE_API_VERSION=<azure api version>

Execution Environment Configuration
===================================

Coder Environment Configuration (Docker vs. Conda)

RD-Agent's coders can execute code in different environments. You can control this behavior by setting environment variables in your ``.env`` file. This is useful for switching between a local Conda environment and an isolated Docker container.

To configure the environment, add the corresponding line to your ``.env`` file based on the scenario you are running.

**For the Model (Quant) Scenario:**

The execution environment is determined by the ``MODEL_COSTEER_ENV_TYPE`` variable, which is read from ``rdagent/components/coder/model_coder/conf.py``.

*   **To use Docker** (recommended for isolated execution):

    .. code-block:: properties

       MODEL_COSTEER_ENV_TYPE=docker

*   **To use Conda** (for running in a local Conda environment):

    .. code-block:: properties

       MODEL_COSTEER_ENV_TYPE=conda

**For the Data Science Scenario:**

The execution environment is determined by the ``DS_CODER_COSTEER_ENV_TYPE`` variable, which is read from ``rdagent/components/coder/data_science/conf.py``.

*   **To use Docker** (recommended for isolated execution):

    .. code-block:: properties

       DS_CODER_COSTEER_ENV_TYPE=docker

*   **To use Conda** (for running in a local Conda environment):

    .. code-block:: properties

       DS_CODER_COSTEER_ENV_TYPE=conda


Custom Time Segment Configuration (Train / Valid / Test)
=========================================================

RD-Agent now supports user-defined time segments for training, validation,
and testing (backtesting). Users can customize these segments via environment
variables in the ``.env`` file, depending on the scenario being executed.

This feature allows greater flexibility when running experiments on different
time ranges without modifying code or YAML configurations.

Fin-Factor Scenario
-------------------

When running the **fin_factor** scenario, you can configure the time segments
using the following environment variables. These variables are read by the
Factor-related PropSettings and directly affect the execution process.

Add the following entries to your ``.env`` file as needed:

.. code-block:: properties

   QLIB_FACTOR_TRAIN_START=<train start date, default is 2008-01-01>
   QLIB_FACTOR_TRAIN_END=<train end date, default is 2014-12-31>
   QLIB_FACTOR_VALID_START=<valid start date, default is 2015-01-01>
   QLIB_FACTOR_VALID_END=<valid end date, default is 2016-12-31>
   QLIB_FACTOR_TEST_START=<test / backtest start date, default is 2017-01-01>
   QLIB_FACTOR_TEST_END=<test / backtest end date, default is 2020-12-31>

Fin-Model Scenario
------------------

When running the **fin_model** scenario, the model training, validation, and
testing time segments can be configured independently via the following
environment variables:

.. code-block:: properties

   QLIB_MODEL_TRAIN_START=<train start date, default is 2008-01-01>
   QLIB_MODEL_TRAIN_END=<train end date, default is 2014-12-31>
   QLIB_MODEL_VALID_START=<valid start date, default is 2015-01-01>
   QLIB_MODEL_VALID_END=<valid end date, default is 2016-12-31>
   QLIB_MODEL_TEST_START=<test / backtest start date, default is 2017-01-01>
   QLIB_MODEL_TEST_END=<test / backtest end date, default is 2020-12-31>

These settings are used during model training and evaluation and directly
impact the execution workflow.

Fin-Quant Scenario
------------------

When running the **fin_quant** scenario, RD-Agent supports configuring time
segments for factor, model, and quant stages simultaneously.

**Note:** The ``QLIB_QUANT_*`` variables are only used for front-end UI display
purposes and do **not** affect the actual execution process.

You may configure the following variables in your ``.env`` file:

.. code-block:: properties

   QLIB_FACTOR_TRAIN_START=<train start date, default is 2008-01-01>
   QLIB_FACTOR_TRAIN_END=<train end date, default is 2014-12-31>
   QLIB_FACTOR_VALID_START=<valid start date, default is 2015-01-01>
   QLIB_FACTOR_VALID_END=<valid end date, default is 2016-12-31>
   QLIB_FACTOR_TEST_START=<test / backtest start date, default is 2017-01-01>
   QLIB_FACTOR_TEST_END=<test / backtest end date, default is 2020-12-31>

   QLIB_MODEL_TRAIN_START=<train start date, default is 2008-01-01>
   QLIB_MODEL_TRAIN_END=<train end date, default is 2014-12-31>
   QLIB_MODEL_VALID_START=<valid start date, default is 2015-01-01>
   QLIB_MODEL_VALID_END=<valid end date, default is 2016-12-31>
   QLIB_MODEL_TEST_START=<test / backtest start date, default is 2017-01-01>
   QLIB_MODEL_TEST_END=<test / backtest end date, default is 2020-12-31>

   QLIB_QUANT_TRAIN_START=<train start date, default is 2008-01-01>
   QLIB_QUANT_TRAIN_END=<train end date, default is 2014-12-31>
   QLIB_QUANT_VALID_START=<valid start date, default is 2015-01-01>
   QLIB_QUANT_VALID_END=<valid end date, default is 2016-12-31>
   QLIB_QUANT_TEST_START=<test / backtest start date, default is 2017-01-01>
   QLIB_QUANT_TEST_END=<test / backtest end date, default is 2020-12-31>

This setup allows the front-end to display consistent segment information
across different stages while keeping execution logic unchanged.
