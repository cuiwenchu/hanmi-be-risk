#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(rxode2))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) {
  stop("usage: pkpd_rxode2.R input.json output.json")
}

input_path <- args[[1]]
output_path <- args[[2]]
payload <- fromJSON(input_path, simplifyVector = TRUE)

ec50 <- as.numeric(payload$pkpd$ec50_ng_ml)
hill <- as.numeric(payload$pkpd$hill)
emax <- as.numeric(payload$pkpd$emax)
times <- as.numeric(payload$pbpk$times)
concs <- as.numeric(payload$pbpk$concs)
interval_hours <- as.numeric(payload$dosing$interval_hours)
dose_mg <- as.numeric(payload$dosing$dose_mg)

if (!is.finite(ec50) || ec50 <= 0) {
  ec50 <- 100
}
if (!is.finite(hill) || hill <= 0) {
  hill <- 1.2
}
if (!is.finite(emax) || emax <= 0) {
  emax <- 100
}

mod <- rxode2({
  Ceff <- conc;
  effect <- emax * (Ceff^hill) / (ec50^hill + Ceff^hill);
})

events <- data.frame(time = times, conc = concs)
sim <- rxSolve(
  mod,
  params = c(ec50 = ec50, hill = hill, emax = emax),
  events = events,
  keep = "conc"
)

df <- as.data.frame(sim)
effect_curve <- lapply(seq_len(nrow(df)), function(i) {
  list(
    time_h = round(as.numeric(df$time[[i]]), 2),
    effect_pct = round(as.numeric(df$effect[[i]]), 2),
    conc_ng_ml = round(as.numeric(df$conc[[i]]), 2)
  )
})

mec <- round(ec50 * 0.8, 2)
mtc <- round(ec50 * 6.0, 2)
target_attainment <- round(mean(df$conc >= mec), 2)
therapeutic_index <- round(mtc / max(mec, 1.0), 2)
recommended_regimen <- ifelse(target_attainment < 0.35 && interval_hours >= 24, "BID", "QD")
recommended_starting_dose_mg <- round(dose_mg * ifelse(target_attainment > 0.7, 0.75, 1.25), 1)

result <- list(
  model_backend = list(
    backend = "rxode2",
    engine = as.character(packageVersion("rxode2"))
  ),
  model = list(
    type = "Emax",
    mechanism = payload$pkpd$mechanism,
    EC50 = list(value = round(ec50, 2), unit = "ng/mL"),
    Emax = list(value = round(emax, 2), unit = "%"),
    Hill = round(hill, 2)
  ),
  dose_optimization = list(
    MEC = list(value = mec, unit = "ng/mL"),
    MTC = list(value = mtc, unit = "ng/mL"),
    therapeutic_index = therapeutic_index,
    target_attainment = target_attainment,
    recommended_regimen = recommended_regimen,
    recommended_starting_dose_mg = recommended_starting_dose_mg
  ),
  effect_time_curve = effect_curve,
  go_no_go = list(
    therapeutic_index = ifelse(therapeutic_index < 2.0, "high-risk", "go"),
    target_attainment = ifelse(target_attainment < 0.3, "review", "go")
  )
)

write_json(result, output_path, auto_unbox = TRUE, pretty = TRUE)
