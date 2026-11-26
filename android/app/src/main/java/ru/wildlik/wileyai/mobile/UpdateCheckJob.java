package ru.wildlik.wileyai.mobile;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

public final class UpdateCheckJob extends JobService {
    private static final int ID = 17832;
    private volatile JobParameters active;

    static void schedule(Context context) {
        JobScheduler jobs = context.getSystemService(JobScheduler.class);
        if (jobs == null) return;
        if (!ReleaseUpdates.enabled(context) || !ReleaseUpdates.configured()) {
            jobs.cancel(ID);
            return;
        }
        if (jobs.getPendingJob(ID) == null) {
            jobs.schedule(new JobInfo.Builder(ID, new ComponentName(context, UpdateCheckJob.class))
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPersisted(true).setPeriodic(6 * 3600_000L).build());
        }
    }

    @Override public boolean onStartJob(JobParameters job) {
        active = job;
        ReleaseUpdates.run(() -> {
            if (active != job) return;
            ReleaseUpdates.check(getApplicationContext(), false);
            if (active == job) jobFinished(job, false);
        });
        return true;
    }

    @Override public boolean onStopJob(JobParameters job) {
        active = null;
        return false;
    }
}
