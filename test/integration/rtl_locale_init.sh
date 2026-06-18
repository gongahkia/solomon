#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if command -v zsh >/dev/null 2>&1; then
  zsh -fc "LC_ALL=ar_EG.UTF-8; export LC_ALL; source '$root/init/shisa.zsh'; [[ \${SHISA_RTL} == 1 ]]"
  zsh -fc "SHISA_RTL=0; LC_ALL=ar_EG.UTF-8; export SHISA_RTL LC_ALL; source '$root/init/shisa.zsh'; [[ \${SHISA_RTL} == 0 ]]"
fi

if command -v bash >/dev/null 2>&1; then
  bash --noprofile --norc -c "LC_ALL=he_IL.UTF-8; export LC_ALL; source '$root/init/shisa.bash'; [[ \${SHISA_RTL} == 1 ]]"
  bash --noprofile --norc -c "LC_ALL=en_US.UTF-8; export LC_ALL; source '$root/init/shisa.bash'; [[ \${SHISA_RTL} == 0 ]]"
fi

if command -v fish >/dev/null 2>&1; then
  fish --no-config -c "set -gx LC_ALL fa_IR.UTF-8; source '$root/init/shisa.fish'; test \"\$SHISA_RTL\" = 1"
  fish --no-config -c "set -gx SHISA_RTL 0; set -gx LC_ALL fa_IR.UTF-8; source '$root/init/shisa.fish'; test \"\$SHISA_RTL\" = 0"
fi

if command -v nu >/dev/null 2>&1; then
  nu --no-config-file -c "\$env.LC_ALL = 'ur_PK.UTF-8'; source '$root/init/shisa.nu'; if \$env.SHISA_RTL != '1' { exit 1 }"
  nu --no-config-file -c "\$env.SHISA_RTL = '0'; \$env.LC_ALL = 'ur_PK.UTF-8'; source '$root/init/shisa.nu'; if \$env.SHISA_RTL != '0' { exit 1 }"
fi

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoLogo -NoProfile -Command "\$env:LC_ALL = 'ar_EG.UTF-8'; . '$root/init/shisa.ps1'; if (\$env:SHISA_RTL -ne '1') { exit 1 }"
  pwsh -NoLogo -NoProfile -Command "\$env:SHISA_RTL = '0'; \$env:LC_ALL = 'ar_EG.UTF-8'; . '$root/init/shisa.ps1'; if (\$env:SHISA_RTL -ne '0') { exit 1 }"
fi
