// Thin CLI around the unmodified KiCad 10.0.0 transmission-line engine.
// KiCad source under reference/kicad-10.0.0-transline is GPL-2.0-or-later.
#include <transline_calculations/coupled_microstrip.h>
#include <cstdio>
#include <cstdlib>
#include <cmath>
int main(int argc,char**argv) {
    if(argc!=7) {std::fprintf(stderr,"usage: impedance width_mm gap_mm h_mm copper_mm er frequency_hz\n");return 2;}
    double v[6];for(int i=0;i<6;i++){char*end=nullptr;v[i]=std::strtod(argv[i+1],&end);if(!end||*end||!std::isfinite(v[i])||v[i]<=0)return 2;}
    using P=TRANSLINE_PARAMETERS;COUPLED_MICROSTRIP c;
    c.SetParameter(P::PHYS_WIDTH,v[0]*.001);c.SetParameter(P::PHYS_S,v[1]*.001);
    c.SetParameter(P::H,v[2]*.001);c.SetParameter(P::T,v[3]*.001);
    c.SetParameter(P::EPSILONR,v[4]);c.SetParameter(P::FREQUENCY,v[5]);
    c.SetParameter(P::H_T,100.);c.SetParameter(P::PHYS_LEN,.05);
    c.SetParameter(P::MURC,1.);c.SetParameter(P::SIGMA,5.8e7);
    c.SetParameter(P::ROUGH,0.);c.SetParameter(P::TAND,.02);
    c.Analyse();const auto&r=c.GetAnalysisResults();
    for(P p:{P::Z0_E,P::Z0_O})if(r.at(p).second!=TRANSLINE_STATUS::OK)return 1;
    double z=r.at(P::Z_DIFF).first;if(!std::isfinite(z)||z<=0)return 1;
    std::printf("{\"zdiff_quasistatic_ohm\":%.8f,\"zdiff_frequency_ohm\":%.8f,\"zeven_frequency_ohm\":%.8f}\n",z,2*c.GetParameter(P::Z0_O),c.GetParameter(P::Z0_E));
}
