#!/usr/bin/env bash

NAMESPACE=amd-llm

function show_logs() {
  local pod_name="$1"
  local mega_or_micro_service="$2"
  # printf "\n POD=$pod_name\n"

  local label
  case $mega_or_micro_service in
    micro)
      label="io.kompose.network/chatqna-default=true"
      ;;
    mega)
      label="io.kompose.network/amd-default=true"
      ;;
  esac

  #set -x
  #printf "\n searching for pod_name=$pod_name\n"
  local RUNNING_PODS=$(oc get pods -n $NAMESPACE -l $label --field-selector status.phase=Running)
  # printf "\n$RUNNING_PODS\n"

  pod=$(echo "$RUNNING_PODS" | awk -v pattern="^$pod_name" '$1 ~ pattern {print $1}')
  #set +x
  printf "\n -> Streaming logs from [$pod]\n"

  oc logs -f "$pod" -n $NAMESPACE

  unset NAMESPACE
}


#============================================================================
# Script to tail the logs for either a given pod or all the main pods running
# in ChatQnA.
#
# author: sgahlot
#============================================================================


#------------------------------------------------------------------------------------------------------------------
# Main function
#
# Command line arguments expected:
#   -d|D    dataprep
#   -e|E    embedding
#   -r|R    reranking
#   -i|I    retriever
#   -l|L    llm
#   -te|TE  tei-embedding
#   -tr|TR  tei-reranker
#   -c|C    chatqna
#------------------------------------------------------------------------------------------------------------------
function process_cmd_args() {
  if [ $# -eq 0 ]; then
      USAGE
  fi

  # dataprep(dD), embedding(eE), reranking(rR), retriever(iI), llm(lL), backend(bB)
  local pod_name
  local mega_or_micro_service="micro"

  while getopts "p:P:" arg
  do
    case $arg in
      p|P)
        case "$OPTARG" in
          d|D)
            pod_name='dataprep'
            ;;
          e|E)
            pod_name='embedding'
            ;;
          r|R)
            pod_name='reranking'
            ;;
          i|I)
            pod_name='retriever'
            ;;
          l|L)
            pod_name='llm'
            ;;
          [cC])
            pod_name='chatqna-backend'
            mega_or_micro_service="mega"
            ;;
          [uU])
            pod_name='chatqna-ui'
            mega_or_micro_service="mega"
            ;;
          [tT][eE])
            pod_name='tei-embedding'
            ;;
          [tT][rR])
            pod_name='tei-reranker'
            ;;
          *)
            incorrectUsageMessage="** INVALID option: [$OPTARG] **"
            USAGE "$incorrectUsageMessage"
            ;;
        esac
        ;;
      *)
        incorrectUsageMessage="** INVALID option: [$arg] **"
        USAGE "$incorrectUsageMessage"
        ;;
    esac
  done

  show_logs "$pod_name" "$mega_or_micro_service"
}

#------------------------------------------------------------------------------------------------------------------
# Displays usage and exits
#
# @param message to display before usage
#------------------------------------------------------------------------------------------------------------------
function USAGE() {
  local incorrectUsageMessage="$1"
  cat <<- USAGE_INFO
    $incorrectUsageMessage
    Script to show logs for a given pod

    Usage: $0 -[p|P] <option>
    where option is:
        -d|D    dataprep        (micro-service)
        -e|E    embedding       (micro-service)
        -r|R    reranking       (micro-service)
        -i|I    retriever       (micro-service)
        -l|L    llm             (micro-service)
        -te|TE  tei-embedding   (embedding micro-service uses this)
        -tr|TR  tei-reranker    (reranking micro-service uses this)
        -c|C    chatqna         (mega-service)
        -u|U    chatqna-ui      (mega-service UI)

    Examples:
      $0 -p d
        Above will show logs for dataprep pod
      $0 -P l
        Above will show logs for llm pod

    Exiting!!!

USAGE_INFO
    exit 1
}

process_cmd_args "$@"