# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SolomonModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

