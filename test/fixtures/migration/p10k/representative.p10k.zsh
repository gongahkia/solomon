typeset -g POWERLEVEL9K_INSTANT_PROMPT=quiet

typeset -g POWERLEVEL9K_LEFT_PROMPT_ELEMENTS=(
  dir
  vcs
  status
  command_execution_time
  background_jobs
  context
  virtualenv
  nodeenv
  go_version
  rust_version
)

typeset -g POWERLEVEL9K_RIGHT_PROMPT_ELEMENTS=(
  aws
  kubecontext
  terraform
  time
  battery
)
