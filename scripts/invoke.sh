#!/usr/bin/env bash


function display_menu_and_get_choice() {
  # Print the menu
  echo "================================================="
  echo "Choose an option: "
  echo "================================================="
  options=(
    "Dataprep - Nike pdf"
    "Dataprep - URL link"
    "Dataprep - Delete ALL"
    "Dataprep - Get ingested data"
    "Embedding"
    "Rerank"
    "Retriever"
    "LLM"
    "ChatQnA - main"
    "Quit"
  )

  # Select an option
  #  COLUMNS=0
  select opt in "${options[@]}"; do
    case $opt in
    "Dataprep - Nike pdf")
      local op='dataprep-ingest-file'
      local endpoint="dataprep/ingest"
      local body_option="-F"
      local file_name='nke-10k-2023.pdf'
      local body="files=@./$file_name"
      local content_type='multipart/form-data'

      printf "\n Adding a knowledge base using [$file_name] document...\n"
      printf '\n Invoking this endpoint will take some time and might time-out as well.'
      printf '\n Try invoking the dataprep get endpoint after a minute (or so) to see the knowledge base...\n'

      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Dataprep - URL link")
      local op='dataprep-ingest-link'
      local endpoint="dataprep/ingest"
      local body_option="-F"
      local link='https://opea.dev'
      local body="link_list=['$link']"
      local content_type='multipart/form-data'

      printf "\n Adding a knowledge base using [$body] link...\n"
      printf '\n Try invoking the dataprep get endpoint after a minute (or so) to see the knowledge base...\n'

      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Dataprep - Delete ALL")
      local op='dataprep-del'
      local endpoint="dataprep/delete"
      local content_type='application/json'
      local body_option="--data"
      local body='{ "file_path": "all" }'

      printf '\n Invoking this endpoint will DELETE all the uploaded files and links\n'

      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Dataprep - Get ingested data")
      local op='dataprep-get'
      local endpoint="dataprep/get"
      local content_type='application/json'
      local body_option="--data"
      local body=""

      printf '\n Invoking this endpoint should return the current knowledge base\n'

      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Embedding")
      local op='embeddings'
      local endpoint="embeddings"
      local body_option="--data"
      local body='{ "input": "what is deep learning?",  "parameters": { "max_new_tokens":64, "do_sample": true } }'
      local content_type='application/json'
      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Rerank")
      local op='reranking'
      local endpoint="reranking"
      local body_option="--data"
      local body='{"initial_query": "what is deep learning?", "retrieved_docs": [ { "text": "Deep Learning is not..." }, { "text":"Deep learning is..." } ]}'
      local content_type='application/json'
      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Retriever")
      local embeddings=$(python -c "import random; embedding = [random.uniform(-1, 1) for _ in range(768)]; print(embedding)")
      local op='retrieve'
      local endpoint="retrieval"
      local body_option="--data"
      local body="{\"text\": \"test\", \"embedding\": ${embeddings}}"
      local content_type='application/json'
      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "LLM")
      local op='llm'
      local endpoint="chat/completions"
      local body_option="--data"
      local body='{ "model": "llama-31b", "messages": "What is Deep Learning?", "max_tokens":17 }'
      local content_type='application/json'
      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "ChatQnA - main")
      local op='chatqna'
      local endpoint="chatqna"
      local body_option="--data"
      local body='{ "messages": "What is the revenue of Nike in 2023?" }'
      local content_type='application/json'
      invoke_endpoint $op $endpoint "$content_type" "$body_option" "$body"
      break
      ;;
    "Quit")
      exit
      ;;
    *) echo "Invalid option $REPLY" ;;
    esac
  done
}

function invoke_endpoint() {
  local svc=$1
  local endpoint=$2
  local content_type=$3
  local body_option=$4
  local body=$5
  local tmp_file=$(mktemp)

  # To see the command (with all the parameters etc.), uncomment the lines with "set +/-x"
  # set -x
  local FULL_ENDPOINT="https://$OCP_HOST/v1/$endpoint"
  printf "\n -> Using '$FULL_ENDPOINT' to invoke '$svc'...\n"
  local response_code=$( curl --max-time 300 -s -S -w '%{response_code}, exitCode=%{exitcode}\n' -X POST $FULL_ENDPOINT --header "Content-Type: $content_type" $body_option "$body" -o $tmp_file )
  # set +x

  local response_body="$(cat $tmp_file)"
  local body_truncated=""
  if [ -n "$response_body" ]; then
    local body_truncated=${response_body:0:55}
    if [ "${response_body}" != "${body_truncated}" ]; then
      body_truncated="${body_truncated}..."
    fi
  fi

  printf "\n statusCode: $response_code"
  if [ -n "$response_body" ]; then
    printf "\n       body: $body_truncated\n"
    if [ "${response_body}" != "${body_truncated}" ]; then
      printf "\n\n Full response body is in [$tmp_file]\n"
    fi
  fi
}


if [ -z "$OCP_HOST" ]; then
  printf '\n Please set "OCP_HOST" environment variable. It should be pointing to the main base-route for each micro-service'
  printf '\n You can use the location of route "chatqna-backend" for setting OCP_HOST'
  printf '\n Exiting!!!\n'
  exit
fi

display_menu_and_get_choice

