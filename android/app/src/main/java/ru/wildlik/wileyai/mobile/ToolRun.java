package ru.wildlik.wileyai.mobile;

import java.util.concurrent.atomic.AtomicBoolean;

/** Immutable approved plan, one pass, four steps, no execution after cancellation or expiry. */
public final class ToolRun {
    private final AndroidTools.Plan plan;private long deadline;private int position;private boolean approved;private final AtomicBoolean cancelled=new AtomicBoolean();
    public ToolRun(AndroidTools.Plan plan){this.plan=plan;}
    public boolean needsConfirmation(){return plan.steps().stream().anyMatch(call->AndroidTools.get(call.tool()).risk()!=AndroidTools.Risk.SAFE_READ);}
    public synchronized void approve(long now){if(cancelled.get()||approved)throw new IllegalStateException("План отменён или уже подтверждён");approved=true;deadline=now+45000;}
    public synchronized void before(AndroidTools.Call call,long now){if(cancelled.get()||!approved||now>deadline||position>=plan.steps().size()||!plan.steps().get(position).equals(call))throw new IllegalStateException("План отменён, изменён или истекло время выполнения");position++;}
    public void cancel(){cancelled.set(true);}
    public boolean cancelled(){return cancelled.get();}
}
