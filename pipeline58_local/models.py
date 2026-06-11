from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ProjectMeta(BaseModel):
    project_name: str = "未命名项目"
    project_code: str = "P58"
    owner: str = "analyst"
    access_level: Literal["internal", "restricted"] = "internal"
    tags: List[str] = Field(default_factory=list)


class DosingRegimen(BaseModel):
    route: Literal["po", "iv"] = "po"
    dose_mg: float = Field(default=50.0, gt=0)
    interval_hours: int = Field(default=24, gt=0)
    repeat_days: int = Field(default=1, gt=0)


class PBPKPopulation(BaseModel):
    species: str = "human"
    preset: Literal["adult", "infant", "child", "adolescent", "elderly", "east_asian_adult", "european_adult", "pregnant_adult", "renal_ckd", "hepatic_cirrhosis"] = "adult"
    ethnicity: Literal["general", "east_asian", "european", "african_ancestry", "latino"] = "general"
    sex: Literal["unknown", "male", "female"] = "unknown"
    weight_kg: float = Field(default=70.0, gt=10)
    age_years: int = Field(default=40, gt=0)
    renal_impairment: bool = False
    hepatic_impairment: bool = False
    pregnant: bool = False
    renal_stage: Literal["normal", "mild", "moderate", "severe"] = "normal"
    hepatic_stage: Literal["normal", "child_pugh_a", "child_pugh_b", "child_pugh_c"] = "normal"
    pregnancy_trimester: Literal["none", "t1", "t2", "t3"] = "none"


class ObservationPoint(BaseModel):
    time_h: float = Field(ge=0)
    conc_ng_ml: Optional[float] = Field(default=None, ge=0)
    effect_pct: Optional[float] = Field(default=None, ge=0)


class ConcomitantDrug(BaseModel):
    name: str = Field(min_length=1)
    role: Literal["perpetrator", "victim", "co-medication"] = "co-medication"
    mechanism: Literal["inhibitor", "inducer", "substrate", "mixed"] = "mixed"
    enzyme: Literal["CYP3A4", "CYP2D6", "Pgp", "OATP1B1", "UGT"] = "CYP3A4"
    strength: Literal["weak", "moderate", "strong"] = "moderate"
    dose_note: str = ""


class FitSettings(BaseModel):
    enable_pk_fit: bool = False
    enable_pd_fit: bool = False
    profile: Literal["quick", "standard", "deep"] = "quick"


class ADMETBatchItem(BaseModel):
    compound_name: str = Field(min_length=1)
    smiles: str = Field(min_length=1)


class ADMETBatchRequest(BaseModel):
    items: List[ADMETBatchItem] = Field(min_length=1, max_length=256)
    chunk_size: int = Field(default=16, ge=1, le=128)
    persist_report: bool = False


class ADMETBatchTaskRequest(BaseModel):
    project_name: str = "ADMET 批量筛选"
    project_code: str = "P58-BATCH"
    notes: str = ""
    items: List[ADMETBatchItem] = Field(min_length=1, max_length=256)


class Pipeline58Request(BaseModel):
    compound_name: str = Field(min_length=1)
    smiles: str = Field(min_length=1)
    target_name: str = Field(default="Unknown target")
    indication: str = Field(default="General")
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    dosing: DosingRegimen = Field(default_factory=DosingRegimen)
    population: PBPKPopulation = Field(default_factory=PBPKPopulation)
    potency_uM: Optional[float] = Field(default=None, gt=0)
    mechanism: Literal["inhibition", "activation"] = "inhibition"
    ddi_notes: List[str] = Field(default_factory=list)
    observations: List[ObservationPoint] = Field(default_factory=list)
    concomitant_drugs: List[ConcomitantDrug] = Field(default_factory=list)
    fit: FitSettings = Field(default_factory=FitSettings)


class Pipeline58RunSummary(BaseModel):
    run_id: str
    compound_name: str
    target_name: str
    created_at: str
    overall_risk: str
    admet_score: int
    recommended_regimen: str
    report_path: str


class Pipeline58RunDetail(BaseModel):
    summary: Pipeline58RunSummary
    request: Dict[str, object]
    result: Dict[str, object]
