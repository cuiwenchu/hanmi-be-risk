#!/usr/bin/env Rscript

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(mrgsolve))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop("usage: pbpk_mrgsolve.R input.json output.json")
input_path <- args[[1]]
output_path <- args[[2]]
payload <- fromJSON(input_path, simplifyVector = TRUE)

safe_num <- function(x, default) {
  n <- suppressWarnings(as.numeric(x))
  if (!is.finite(n)) return(default)
  n
}

route <- as.character(payload$dosing$route)
dose_mg <- safe_num(payload$dosing$dose_mg, 100)
interval_hours <- safe_num(payload$dosing$interval_hours, 24)
repeat_days <- max(1, as.integer(safe_num(payload$dosing$repeat_days, 1)))
total_hours <- safe_num(payload$simulation$total_hours, interval_hours * repeat_days)
compound <- payload$compound
population <- payload$population
weight_kg <- safe_num(population$weight_kg, 70)
vol <- compound$volumes_l
flow <- compound$blood_flows_l_h
kp <- compound$partition_coefficients
gi <- compound$gi_transit_absorption

FABS <- min(max(safe_num(compound$oral_bioavailability, safe_num(payload$admet$oral_f, 0.6)), 0.001), 1)
KA <- max(safe_num(compound$ka_h, safe_num(payload$admet$ka, 1.0)), 0.01)
CLH <- max(safe_num(compound$hepatic_clearance_l_h, safe_num(payload$admet$cl_l_h, 5) * 0.55), 0.001)
CLR <- max(safe_num(compound$renal_clearance_l_h, safe_num(payload$admet$cl_l_h, 5) * 0.45), 0)
FU <- min(max(safe_num(compound$fraction_unbound_plasma, 0.2), 0.001), 1)
BP <- max(safe_num(compound$blood_plasma_ratio, 0.9), 0.1)

VART <- max(safe_num(vol$arterial_blood_l, 1.2), 0.2)
VVEN <- max(safe_num(vol$venous_blood_l, 3.6), 0.5)
VLUNG <- max(safe_num(vol$lung_l, 0.5), 0.1)
VGUT <- max(safe_num(vol$gut_l, 1.2), 0.1)
VLIV <- max(safe_num(vol$liver_l, 1.8), 0.2)
VKID <- max(safe_num(vol$kidney_l, 0.3), 0.1)
VRICH <- max(safe_num(vol$rich_l, 5.0), 0.5)
VMUS <- max(safe_num(vol$muscle_l, 28.0), 1.0)
VFAT <- max(safe_num(vol$fat_l, 15.0), 1.0)
VREST <- max(weight_kg * 0.12, 2)

QGUT <- max(safe_num(flow$gut_flow_l_h, 48), 0.1)
QHA <- max(safe_num(flow$hepatic_artery_flow_l_h, 19.5), 0.1)
QKID <- max(safe_num(flow$kidney_flow_l_h, 57), 0.1)
QRICH <- max(safe_num(flow$rich_flow_l_h, 54), 0.1)
QMUS <- max(safe_num(flow$muscle_flow_l_h, 60), 0.1)
QFAT <- max(safe_num(flow$fat_flow_l_h, 16.5), 0.1)
QREST <- max(safe_num(flow$rest_flow_l_h, 45), 0.1)
QCO <- QGUT + QHA + QKID + QRICH + QMUS + QFAT + QREST

KPGUT <- max(safe_num(kp$gut, 1), 0.01)
KPLIV <- max(safe_num(kp$liver, 1), 0.01)
KPKID <- max(safe_num(kp$kidney, 1), 0.01)
KPLUNG <- max(safe_num(kp$lung, 1), 0.01)
KPRICH <- max(safe_num(kp$rich, 1), 0.01)
KPMUS <- max(safe_num(kp$muscle, 1), 0.01)
KPFAT <- max(safe_num(kp$fat, 4), 0.01)
KPREST <- max(safe_num(kp$rest, 1), 0.01)

KDIS <- max(safe_num(gi$dissolution_h, 0.8), 0.001)
KGE <- max(safe_num(gi$gastric_emptying_h, 1.0), 0.001)
KDUO <- max(safe_num(gi$duodenum_to_jejunum_h, 0.7), 0.001)
KJEJ <- max(safe_num(gi$jejunum_to_ileum_h, 0.55), 0.001)
KILE <- max(safe_num(gi$ileum_to_colon_h, 0.35), 0.001)
KCOLTR <- max(safe_num(gi$colon_transit_h, 0.08), 0.001)
KADUO <- max(safe_num(gi$abs_duodenum_h, KA * 0.55), 0.001)
KAJEJ <- max(safe_num(gi$abs_jejunum_h, KA * 0.95), 0.001)
KAILE <- max(safe_num(gi$abs_ileum_h, KA * 0.65), 0.001)
KACOL <- max(safe_num(gi$abs_colon_h, KA * 0.08), 0.0001)

code <- '
$PARAM FABS=0.6, CLH=3, CLR=2, FU=0.2, BP=0.9,
       VART=1.2, VVEN=3.6, VLUNG=0.5, VGUT=1.2, VLIV=1.8, VKID=0.3, VRICH=5, VMUS=28, VFAT=15, VREST=10,
       QCO=300, QGUT=48, QHA=19.5, QKID=57, QRICH=54, QMUS=60, QFAT=16.5, QREST=45,
       KPGUT=1, KPLIV=1, KPKID=1, KPLUNG=1, KPRICH=1, KPMUS=1, KPFAT=4, KPREST=1,
       KDIS=0.8, KGE=1, KDUO=0.7, KJEJ=0.55, KILE=0.35, KCOLTR=0.08,
       KADUO=0.5, KAJEJ=0.9, KAILE=0.5, KACOL=0.05
$CMT DOSEDEP STOMACH DUODENUM JEJUNUM ILEUM COLON GUT LIVER KIDNEY LUNG RICH MUSCLE FAT REST ART VEN
$MAIN
F_DOSEDEP = 1;
$ODE
double CART = ART / VART;
double CVEN = VEN / VVEN;
double CGUT = GUT / VGUT;
double CLIV = LIVER / VLIV;
double CKID = KIDNEY / VKID;
double CLUNG = LUNG / VLUNG;
double CRICH = RICH / VRICH;
double CMUS = MUSCLE / VMUS;
double CFAT = FAT / VFAT;
double CREST = REST / VREST;
double COUT_GUT = CGUT / KPGUT;
double COUT_LIV = CLIV / KPLIV;
double COUT_KID = CKID / KPKID;
double COUT_LUNG = CLUNG / KPLUNG;
double COUT_RICH = CRICH / KPRICH;
double COUT_MUS = CMUS / KPMUS;
double COUT_FAT = CFAT / KPFAT;
double COUT_REST = CREST / KPREST;
double DISS = KDIS * DOSEDEP;
double GE = KGE * STOMACH;
double TR_DUO = KDUO * DUODENUM;
double TR_JEJ = KJEJ * JEJUNUM;
double TR_ILE = KILE * ILEUM;
double TR_COL = KCOLTR * COLON;
double ABS_DUO = KADUO * DUODENUM;
double ABS_JEJ = KAJEJ * JEJUNUM;
double ABS_ILE = KAILE * ILEUM;
double ABS_COL = KACOL * COLON;
double ABS_TOTAL = FABS * (ABS_DUO + ABS_JEJ + ABS_ILE + ABS_COL);
dxdt_DOSEDEP = -DISS;
dxdt_STOMACH = DISS - GE;
dxdt_DUODENUM = GE - TR_DUO - ABS_DUO;
dxdt_JEJUNUM = TR_DUO - TR_JEJ - ABS_JEJ;
dxdt_ILEUM = TR_JEJ - TR_ILE - ABS_ILE;
dxdt_COLON = TR_ILE - TR_COL - ABS_COL;
dxdt_GUT = QGUT * CART - QGUT * COUT_GUT;
dxdt_LIVER = ABS_TOTAL + QGUT * COUT_GUT + QHA * CART - (QGUT + QHA) * COUT_LIV - CLH * FU * COUT_LIV;
dxdt_KIDNEY = QKID * CART - QKID * COUT_KID - CLR * FU * COUT_KID;
dxdt_RICH = QRICH * CART - QRICH * COUT_RICH;
dxdt_MUSCLE = QMUS * CART - QMUS * COUT_MUS;
dxdt_FAT = QFAT * CART - QFAT * COUT_FAT;
dxdt_REST = QREST * CART - QREST * COUT_REST;
dxdt_LUNG = QCO * CVEN - QCO * COUT_LUNG;
dxdt_ART = QCO * COUT_LUNG - QCO * CART;
dxdt_VEN = (QGUT + QHA) * COUT_LIV + QKID * COUT_KID + QRICH * COUT_RICH + QMUS * COUT_MUS + QFAT * COUT_FAT + QREST * COUT_REST - QCO * CVEN;
$TABLE
double CP = (VEN / VVEN) * 1000 / BP;
double ART_CONC = (ART / VART) * 1000 / BP;
double LUNG_CONC = (LUNG / VLUNG) * 1000;
double GUT_CONC = (GUT / VGUT) * 1000;
double LIVER_CONC = (LIVER / VLIV) * 1000;
double KIDNEY_CONC = (KIDNEY / VKID) * 1000;
double RICH_CONC = (RICH / VRICH) * 1000;
double MUSCLE_CONC = (MUSCLE / VMUS) * 1000;
double FAT_CONC = (FAT / VFAT) * 1000;
double STOMACH_MG = STOMACH;
double DUODENUM_MG = DUODENUM;
double JEJUNUM_MG = JEJUNUM;
double ILEUM_MG = ILEUM;
double COLON_MG = COLON;
double ABSORPTION_RATE_MG_H = ABS_TOTAL;
$CAPTURE CP ART_CONC LUNG_CONC GUT_CONC LIVER_CONC KIDNEY_CONC RICH_CONC MUSCLE_CONC FAT_CONC STOMACH_MG DUODENUM_MG JEJUNUM_MG ILEUM_MG COLON_MG ABSORPTION_RATE_MG_H
'

mod <- mcode("pipeline58_oral_gi_whole_body_pbpk", code) %>%
  param(FABS=FABS, CLH=CLH, CLR=CLR, FU=FU, BP=BP,
        VART=VART, VVEN=VVEN, VLUNG=VLUNG, VGUT=VGUT, VLIV=VLIV, VKID=VKID, VRICH=VRICH, VMUS=VMUS, VFAT=VFAT, VREST=VREST,
        QCO=QCO, QGUT=QGUT, QHA=QHA, QKID=QKID, QRICH=QRICH, QMUS=QMUS, QFAT=QFAT, QREST=QREST,
        KPGUT=KPGUT, KPLIV=KPLIV, KPKID=KPKID, KPLUNG=KPLUNG, KPRICH=KPRICH, KPMUS=KPMUS, KPFAT=KPFAT, KPREST=KPREST,
        KDIS=KDIS, KGE=KGE, KDUO=KDUO, KJEJ=KJEJ, KILE=KILE, KCOLTR=KCOLTR, KADUO=KADUO, KAJEJ=KAJEJ, KAILE=KAILE, KACOL=KACOL)

addl <- max(repeat_days - 1, 0)
event <- if (route == "iv") ev(amt=dose_mg, ii=interval_hours, addl=addl, cmt=16) else ev(amt=dose_mg, ii=interval_hours, addl=addl, cmt=1)
sim <- mod %>% mrgsim(events=event, end=total_hours, delta=0.25)
df <- as.data.frame(sim)
times <- as.numeric(df$time)
conc <- pmax(as.numeric(df$CP), 0)

cmax_idx <- which.max(conc)
cmax_value <- conc[[cmax_idx]]
tmax_value <- times[[cmax_idx]]
auc <- 0
if (length(conc) > 1) for (i in seq_len(length(conc)-1)) auc <- auc + ((conc[[i]] + conc[[i+1]])/2) * (times[[i+1]] - times[[i]])
terminal_points <- tail(seq_along(times), min(8, length(times)))
terminal_conc <- conc[terminal_points]
terminal_time <- times[terminal_points]
valid_terminal <- terminal_conc > 0
if (sum(valid_terminal) >= 3) {
  fit <- lm(log(terminal_conc[valid_terminal]) ~ terminal_time[valid_terminal])
  ke <- max(-coef(fit)[[2]], 1e-6)
} else {
  ke <- max((CLH + CLR) / max(VVEN + VART + VLUNG + VGUT + VLIV + VKID + VRICH + VMUS + VFAT, 1), 1e-6)
}
half_life <- 0.693 / ke
rac <- ifelse(ke > 0, 1 / max(1 - exp(-ke * interval_hours), 0.15), 1)
curve <- lapply(seq_along(times), function(i) {
  list(time_h=round(times[[i]],2), conc_ng_ml=round(conc[[i]],2), arterial_ng_ml=round(max(as.numeric(df$ART_CONC[[i]]),0),2), lung_ng_ml=round(max(as.numeric(df$LUNG_CONC[[i]]),0),2), gut_ng_ml=round(max(as.numeric(df$GUT_CONC[[i]]),0),2), liver_ng_ml=round(max(as.numeric(df$LIVER_CONC[[i]]),0),2), kidney_ng_ml=round(max(as.numeric(df$KIDNEY_CONC[[i]]),0),2), rich_tissue_ng_ml=round(max(as.numeric(df$RICH_CONC[[i]]),0),2), muscle_ng_ml=round(max(as.numeric(df$MUSCLE_CONC[[i]]),0),2), fat_ng_ml=round(max(as.numeric(df$FAT_CONC[[i]]),0),2), stomach_mg=round(max(as.numeric(df$STOMACH_MG[[i]]),0),4), duodenum_mg=round(max(as.numeric(df$DUODENUM_MG[[i]]),0),4), jejunum_mg=round(max(as.numeric(df$JEJUNUM_MG[[i]]),0),4), ileum_mg=round(max(as.numeric(df$ILEUM_MG[[i]]),0),4), colon_mg=round(max(as.numeric(df$COLON_MG[[i]]),0),4), absorption_rate_mg_h=round(max(as.numeric(df$ABSORPTION_RATE_MG_H[[i]]),0),4))
})
max_col <- function(name) round(max(df[[name]], na.rm=TRUE), 4)
result <- list(
  model_backend=list(backend="mrgsolve", engine=as.character(packageVersion("mrgsolve")), model_type="compound-specific oral GI segmented whole-body PBPK", compartments=c("dose_depot","stomach","duodenum","jejunum","ileum","colon","gut_tissue","portal_liver","kidney","lung","rich_tissue","muscle","fat","rest","arterial_blood","venous_blood"), parameterization="ADMET/descriptor-derived oral GI segmented whole-body compound-specific"),
  compound_specific_parameters=compound,
  pk_parameters=list(F=round(FABS,3), Cmax=list(value=round(cmax_value,2), unit="ng/mL"), Tmax=list(value=round(tmax_value,2), unit="h"), AUC0_t=list(value=round(auc,2), unit="ng*h/mL"), t_half=list(value=round(half_life,2), unit="h"), Vss=list(value=round((VART+VVEN+VLUNG+VGUT+VLIV+VKID+VRICH+VMUS+VFAT)/weight_kg,2), unit="L/kg"), CL=list(value=round(CLH+CLR,2), unit="L/h"), hepatic_CL=list(value=round(CLH,2), unit="L/h"), renal_CL=list(value=round(CLR,2), unit="L/h"), Rac=list(value=round(rac,2), unit="ratio")),
  concentration_time_curve=curve,
  gi_segment_summary=list(max_stomach_mg=max_col("STOMACH_MG"), max_duodenum_mg=max_col("DUODENUM_MG"), max_jejunum_mg=max_col("JEJUNUM_MG"), max_ileum_mg=max_col("ILEUM_MG"), max_colon_mg=max_col("COLON_MG"), max_absorption_rate_mg_h=max_col("ABSORPTION_RATE_MG_H"), transit_absorption=gi),
  tissue_exposure_summary=list(max_liver_ng_ml=round(max(df$LIVER_CONC, na.rm=TRUE),2), max_kidney_ng_ml=round(max(df$KIDNEY_CONC, na.rm=TRUE),2), max_fat_ng_ml=round(max(df$FAT_CONC, na.rm=TRUE),2)),
  go_no_go=list(oral_exposure=ifelse(route=="po" && FABS < 0.1, "no-go", "go"), accumulation=ifelse(rac > 3.0, "review", "go"))
)
write_json(result, output_path, auto_unbox=TRUE, pretty=TRUE)
