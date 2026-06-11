# 01 - Prerequisites

## Goal

Ensure you have everything needed before installing the Fusion Data Platform (FDP) on ALCF Polaris.

---

## What You Need

### 1. ALCF Polaris Account

You need an active account on the ALCF Polaris supercomputer.

- Register or check your account status at <https://accounts.alcf.anl.gov/>
- You must be specifically approved for the **Polaris** system. Having an ALCF account alone is not sufficient.
- Account approval may take several business days.

### 2. Project Allocation

You must be a member of the **`fusiondl_aesp`** project allocation on Polaris. This grants you access to the shared Eagle filesystem at `/eagle/fusiondl_aesp/` and allows you to submit jobs charged to the project.

- If you are not already a member, contact the project PI or [ALCF Support](https://www.alcf.anl.gov/support-center/contact-us) to be added.

### 3. SSH Access to Polaris

Verify that you can log in to a Polaris login node:

```bash
ssh <username>@polaris.alcf.anl.gov
```

Replace `<username>` with your ALCF username. If this command hangs or is refused, troubleshoot your SSH configuration or contact ALCF support.

### 4. FDP Bearer Token

This is a JWT (JSON Web Token) that authenticates you against the Pelican/OSDF CDN to download DIII-D PTDATA archives. Without it, data fetches will fail with `403 Forbidden` errors.

**How to get a token:**

- Request one from Brian on the GA-FDP team, or fill out the request form at <https://forms.office.com/g/wEaBDGqqq8>
- Tokens are valid for approximately **1 month** from the issue date. You will need to request a new one when it expires.

**Once you have your token, place it on Polaris:**

```bash
mkdir -p ~/.fdp
# Paste your token into the file (one line, no trailing newline):
echo 'YOUR_TOKEN_STRING_HERE' > ~/.fdp/token
chmod 600 ~/.fdp/token
```

**Verify the token is in place:**

```bash
cat ~/.fdp/token | head -c 40
```

The output should show a JWT string starting with `eyJ`. If you see something else, double-check that you copied the full token without extra whitespace or newlines.

### 5. Familiarity with PBS Job Submission

FDP jobs run on Polaris compute nodes via PBS. You should be comfortable with basic PBS commands:

- `qsub` -- submit a job
- `qstat` -- check job status
- `qdel` -- cancel a job

If you are new to PBS on Polaris, review the [ALCF Job Scheduling and Execution documentation](https://docs.alcf.anl.gov/polaris/queueing-and-running-jobs/job-and-queue-scheduling/).

---

## Verify

Before proceeding, confirm all of the following:

- [ ] You can SSH into `polaris.alcf.anl.gov` successfully
- [ ] You are a member of the `fusiondl_aesp` project allocation
- [ ] Your FDP bearer token is saved at `~/.fdp/token` and starts with `eyJ`
- [ ] You are familiar with `qsub`, `qstat`, and `qdel`

---

## Next

Continue to [02 - Installation](02_INSTALLATION.md).
