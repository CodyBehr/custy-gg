// Working name for the beta. Change it here (and in the Vercel project name) once the real name is picked.
export const BRAND = "Fogline";
export const TAGLINE = "Clear the fog on your games.";

// The Windows app. During the beta it is still served (and updated) by custy.gg's backend;
// set COACH_DOWNLOAD_URL in Vercel to point somewhere else later (e.g. a Microsoft Store link).
export const DOWNLOAD_URL = process.env.COACH_DOWNLOAD_URL || "https://custy-gg.vercel.app/api/coach/windows";
