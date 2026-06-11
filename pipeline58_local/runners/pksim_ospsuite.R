#!/usr/bin/env Rscript
suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(ospsuite))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("usage: pksim_ospsuite.R input.json output.json")
input_path <- args[[1]]
output_path <- args[[2]]
payload <- fromJSON(input_path, simplifyVector = TRUE)
`%||%` <- function(a, b) { if (is.null(a) || (is.character(a) && !nzchar(a))) return(b); a }
safe_num <- function(v, default) {
  if (is.null(v) || length(v) == 0) return(default)
  n <- suppressWarnings(as.numeric(v)[1])
  if (length(n) == 0 || !is.finite(n)) return(default)
  n
}
first_match <- function(paths, pattern) { m <- paths[grepl(pattern, paths, ignore.case=TRUE)]; if (length(m)>0) m[[1]] else "" }

pkml_path <- payload$pkml_path
if (is.null(pkml_path) || !nzchar(pkml_path)) pkml_path <- system.file("extdata", "Aciclovir.pkml", package = "ospsuite")
if (!file.exists(pkml_path)) stop(paste("pkml not found:", pkml_path))
route <- tolower(as.character(payload$route %||% "po"))
dose_mg <- safe_num(payload$dose_mg, 500)
interval_hours <- safe_num(payload$interval_hours, 24)
repeat_days <- max(1, as.integer(safe_num(payload$repeat_days, 1)))
total_hours <- safe_num(payload$total_hours, 72)
if (!is.finite(total_hours) || total_hours <= 0) total_hours <- 72
compound_params <- payload$compound_parameters
if (is.null(compound_params) || !is.list(compound_params)) compound_params <- list()

sim <- loadSimulation(pkml_path)
warnings <- c()
parameter_updates <- list()
all_parameter_paths <- getAllParameterPathsIn(sim)
mw_paths <- all_parameter_paths[grepl("^[^|]+\\|Molecular weight$", all_parameter_paths)]
if (length(mw_paths) > 0) {
  template_molecule <- strsplit(mw_paths[[1]], "\\|")[[1]][1]
} else {
  molecule_paths <- getAllMoleculePathsIn(sim)
  template_molecule <- if (length(molecule_paths) > 0) tail(strsplit(molecule_paths[[1]], "\\|")[[1]], 1) else "Aciclovir"
}
compound_name <- as.character(payload$compound_name %||% template_molecule)

set_one <- function(label, path, value, unit=NULL) {
  if (!nzchar(path) || is.null(value) || !is.finite(suppressWarnings(as.numeric(value)))) return(FALSE)
  ok <- tryCatch({
    if (is.null(unit)) setParameterValuesByPath(path, as.numeric(value), sim, stopIfNotFound=FALSE)
    else setParameterValuesByPath(path, as.numeric(value), sim, units=unit, stopIfNotFound=FALSE)
    TRUE
  }, error=function(e) { warnings <<- c(warnings, paste(label, conditionMessage(e), sep=": ")); FALSE })
  if (ok) parameter_updates[[length(parameter_updates)+1]] <<- list(label=label, path=path, value=as.numeric(value), unit=unit %||% "base")
  ok
}

mw <- safe_num(compound_params$molecular_weight, NA)
logp <- safe_num(compound_params$logP, NA)
logs <- safe_num(compound_params$log_solubility, NA)
renal_cl <- safe_num(compound_params$renal_clearance_l_h, NA)
kidney_vol <- safe_num(compound_params$volumes_l$kidney_l, 0.31)
if (is.finite(mw)) set_one("molecular_weight", paste0(template_molecule, "|Molecular weight"), mw, "g/mol")
if (is.finite(logp)) set_one("lipophilicity", paste0(template_molecule, "|Lipophilicity"), logp, "Log Units")
if (is.finite(logs) && is.finite(mw)) {
  sol_mg_l <- max(10^logs * mw * 1000, 1e-6)
  set_one("solubility_ref_ph", paste0(template_molecule, "|Solubility at reference pH"), sol_mg_l, "mg/l")
}
dose_path <- first_match(all_parameter_paths, "Applications\\|.*ProtocolSchemaItem\\|Dose$")
set_one("dose", dose_path, dose_mg, "mg")
infusion_path <- first_match(all_parameter_paths, "Applications\\|.*ProtocolSchemaItem\\|Infusion time$")
if (route == "iv") set_one("infusion_time", infusion_path, 10, "min")
if (is.finite(renal_cl)) {
  ts_path <- first_match(all_parameter_paths, paste0("Kidney.*", template_molecule, ".*TSspec$"))
  ts_spec <- max((renal_cl / max(kidney_vol, 0.05)) / 60, 0)
  set_one("renal_tubular_secretion_proxy", ts_path, ts_spec, "1/min")
}
if (route != "iv") warnings <- c(warnings, "Current default PKML template is IV Aciclovir; oral route requires an oral PK-Sim/MoBi template for route-exact simulation.")

export_pkml_path <- as.character(payload$export_pkml_path %||% "")
if (nzchar(export_pkml_path)) {
  tryCatch(saveSimulation(sim, export_pkml_path), error=function(e) warnings <<- c(warnings, paste("saveSimulation", conditionMessage(e), sep=": ")))
}

res <- runSimulation(sim)
df <- simulationResultsToDataFrame(res)
if (nrow(df) == 0) stop("empty simulation result")
path_filter <- payload$path_filter
selected_path <- ""
all_paths <- unique(df$paths)
if (!is.null(path_filter) && nzchar(path_filter)) {
  matched <- all_paths[grepl(path_filter, all_paths, ignore.case=TRUE)]
  if (length(matched) > 0) selected_path <- matched[[1]]
}
if (!nzchar(selected_path)) selected_path <- all_paths[[1]]
sub <- df[df$paths == selected_path, c("Time", "simulationValues", "TimeUnit")]
if (nrow(sub) == 0) stop("no rows after path filter")
convert_to_h <- function(v, unit) {
  u <- tolower(trimws(as.character(unit)))
  if (u %in% c("h","hour","hours")) return(as.numeric(v))
  if (u %in% c("min","minute","minutes")) return(as.numeric(v)/60)
  if (u %in% c("s","sec","second","seconds")) return(as.numeric(v)/3600)
  if (u %in% c("d","day","days")) return(as.numeric(v)*24)
  as.numeric(v)
}
time_h <- convert_to_h(sub$Time, sub$TimeUnit[1])
conc <- as.numeric(sub$simulationValues)
valid <- is.finite(time_h) & is.finite(conc)
sub2 <- data.frame(time_h=time_h[valid], conc=conc[valid])
sub2 <- sub2[order(sub2$time_h),]
sub2 <- sub2[sub2$time_h <= total_hours,]
if (nrow(sub2) < 2) stop("insufficient points for profile")
cmax_idx <- which.max(sub2$conc); cmax <- sub2$conc[cmax_idx]; tmax <- sub2$time_h[cmax_idx]
auc <- 0
for (i in 1:(nrow(sub2)-1)) auc <- auc + (sub2$conc[i+1] + sub2$conc[i]) * 0.5 * (sub2$time_h[i+1] - sub2$time_h[i])
curve <- lapply(seq_len(nrow(sub2)), function(i) list(time_h=round(sub2$time_h[i],4), conc=round(sub2$conc[i],6)))

out <- list(
  backend=list(engine="ospsuite", model="PK-Sim", pkml=pkml_path, template_molecule=template_molecule, mapped_compound=compound_name, generated_pkml=export_pkml_path),
  selected_path=selected_path,
  pk=list(Cmax=list(value=round(cmax,6), unit="model-unit"), Tmax=list(value=round(tmax,4), unit="h"), AUC0_t=list(value=round(auc,6), unit="model-unit*h")),
  concentration_time_curve=curve,
  pkml_mapping=list(source_run_id=payload$source_run_id %||% "", parameter_updates=parameter_updates, warnings=warnings, compound_parameters=compound_params),
  oral_gi=list(enabled=FALSE, reason="OSPSuite PKML template run; use PK-Sim/MoBi oral template for GI route-exact PBBM."),
  meta=list(total_hours=total_hours, points=nrow(sub2), generated_at=format(Sys.time(), "%Y-%m-%dT%H:%M:%S"))
)
write(toJSON(out, auto_unbox=TRUE, pretty=TRUE), file=output_path)
