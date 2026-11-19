#include "host_admission_ui.h"
#include <cassert>
#include <cstring>
#include <iostream>

using gobot_host::AdmissionUi;
using gobot_host::AdmissionUpdate;
using gobot_host::NativeRenderResult;

int main() {
    AdmissionUi ui;
    assert(!ui.Known() && !ui.InputAllowed() && !ui.KnownBlocked());
    assert(!ui.ShouldShowNotice(true,true,false,false));
    assert(!ui.ObserveRender(NativeRenderResult::Invalidated,false,0));

    // A stale/foreign scope and unnegotiated v1 never alter the current view.
    assert(ui.Update(false,true,0,"scope_expired","expert")==AdmissionUpdate::Ignored);
    assert(ui.Update(true,false,0,"scope_expired","expert")==AdmissionUpdate::Ignored);
    assert(!ui.Known());
    assert(ui.Update(true,true,1,"available","fast")==AdmissionUpdate::Accepted);
    const auto available_revision=ui.Revision();
    assert(ui.InputAllowed() && !ui.KnownBlocked() && !*ui.NoticeText());
    assert(ui.Update(true,false,-1,"untrusted text","foreign")==AdmissionUpdate::Ignored);
    assert(ui.InputAllowed() && ui.Revision()==available_revision);
    assert(ui.Update(true,true,1,"available","fast")==AdmissionUpdate::Accepted);
    assert(ui.Revision()==available_revision);

    // Every fixed server denial remains a persistent idle notice, without a
    // timer/counter that could turn it back into an apparently ready screen.
    const char* codes[]={"scope_expired","starts_exhausted","consent_required","unavailable"};
    const char* notices[]={"Время теста истекло","Лимит исчерпан","Нужно разрешение","Разговор недоступен"};
    for(unsigned index=0;index<4;++index) {
        assert(ui.Update(true,true,0,codes[index],"expert")==AdmissionUpdate::Accepted);
        assert(ui.KnownBlocked() && !ui.InputAllowed());
        assert(!std::strcmp(ui.CodeName(),codes[index]));
        assert(!std::strcmp(ui.NoticeText(),notices[index]));
        assert(!std::strcmp(ui.NoticeDetail(),"Экспертный режим"));
        for(unsigned tick=0;tick<10000;++tick)assert(ui.ShouldShowNotice(true,true,false,false));
        assert(!ui.ShouldShowNotice(false,true,false,false)); // disconnected
        assert(!ui.ShouldShowNotice(true,false,false,false)); // listening/output
        assert(!ui.ShouldShowNotice(true,true,true,false));   // mute
        assert(!ui.ShouldShowNotice(true,true,false,true));   // timer/priority view
    }

    // Malformed JSON booleans, contradictions, non-enum strings and missing
    // fields cannot preserve or create an optimistic Available indication.
    struct Bad {int token;const char* code;const char* mode;};
    const Bad invalid[]={{-1,"available","fast"},{2,"available","fast"},
        {0,"available","fast"},{1,"scope_expired","fast"},
        {0,"arbitrary provider error","fast"},{0,nullptr,"fast"},
        {1,"available","FAST"},{0,"scope_expired",nullptr},
        {1,"available","device-owner"}};
    for(const auto& bad:invalid) {
        assert(ui.Update(true,true,1,"available","fast")==AdmissionUpdate::Accepted);
        assert(ui.Update(true,true,bad.token,bad.code,bad.mode)==AdmissionUpdate::Invalid);
        assert(ui.KnownBlocked() && !std::strcmp(ui.CodeName(),"unavailable"));
        assert(!std::strcmp(ui.NoticeText(),"Разговор недоступен"));
    }

    // Native receipts distinguish a framebuffer submission from unchanged
    // content. Allocation failure emits no successful rendering receipt.
    ui.Reset();
    assert(ui.Update(true,true,0,"scope_expired","fast")==AdmissionUpdate::Accepted);
    assert(!ui.ObserveRender(NativeRenderResult::Failed,true,7));
    assert(!ui.RenderedNotice());
    assert(ui.ObserveRender(NativeRenderResult::Invalidated,true,7));
    assert(ui.RenderedNotice() && ui.NativeView()==7);
    assert(!std::strcmp(ui.RenderEvidence(),"native_framebuffer_invalidated"));
    assert(!ui.ObserveRender(NativeRenderResult::Unchanged,true,7));
    assert(!std::strcmp(ui.RenderEvidence(),"native_framebuffer_unchanged"));
    // Timer and playback take the screen; the denial remains stored.
    assert(ui.ObserveRender(NativeRenderResult::Invalidated,false,9));
    assert(!ui.RenderedNotice() && ui.KnownBlocked());
    assert(ui.ObserveRender(NativeRenderResult::Invalidated,false,4));
    assert(ui.ObserveRender(NativeRenderResult::Invalidated,true,7));
    assert(ui.RenderedNotice());
    const auto blocked_revision=ui.Revision();
    assert(ui.Update(true,true,1,"available","fast")==AdmissionUpdate::Accepted);
    assert(ui.Revision()>blocked_revision && !ui.KnownBlocked());
    assert(ui.ObserveRender(NativeRenderResult::Invalidated,true,0));
    assert(!ui.RenderedNotice()); // Allowed can never ACK a denial notice.
    assert(!ui.ShouldShowNotice(true,true,false,false));

    // A new connection/fault cannot inherit the old transport's eligibility.
    ui.Reset();
    assert(!ui.Known() && !ui.InputAllowed() && !ui.KnownBlocked());
    assert(!ui.RenderedNotice() && ui.NativeView()==0);
    assert(ui.RenderResult()==NativeRenderResult::Failed);
    assert(!ui.ObserveRender(NativeRenderResult::Unchanged,false,0));
    assert(!std::strcmp(ui.CodeName(),"unknown"));
    std::cout<<"PASS admission scope/types/enums/persistence/native receipts; bytes="<<sizeof(AdmissionUi)<<'\n';
}
