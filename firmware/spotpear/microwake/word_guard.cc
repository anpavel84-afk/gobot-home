// Offline prototype of a complete-word acoustic guard. No I/O or model actions.
#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>
#ifdef _WIN32
#define EXPORT __declspec(dllexport)
#else
#define EXPORT
#endif
extern "C" EXPORT int word_guard_scores(const float* models,int count,int length,int dims,
    const float* frames,int n,int recent,int min_duration,int max_duration,float* scores) {
    if(!models||!frames||!scores||count<1||count>128||length<4||length>128||dims<1||dims>40||n<1||n>2000||recent<1||min_duration<1||max_duration<min_duration)return -1;
    const float inf=std::numeric_limits<float>::infinity();
    std::vector<float> previous(length+1),older(length+1),current(length+1),cost(length+1),last_cost(length+1);
    std::vector<int> start_previous(length+1),start_older(length+1),start_current(length+1);
    for(int k=0;k<count;++k) {
        std::fill(previous.begin(),previous.end(),inf);previous[0]=0;older=previous;
        std::fill(start_previous.begin(),start_previous.end(),0);float best=inf;
        for(int j=0;j<n;++j) {
            current[0]=0;start_current[0]=j;
            for(int i=1;i<=length;++i) {
                float dot=0;const float* a=models+(k*length+i-1)*dims;const float* b=frames+j*dims;
                for(int d=0;d<dims;++d)dot+=a[d]*b[d];
                if(!std::isfinite(dot))return -2;
                cost[i]=std::max(0.f,1.f-std::min(1.f,dot));
                float value=previous[i-1]+2*cost[i];int first=i==1?j:start_previous[i-1];
                if(i>=2 && previous[i-2]+cost[i-1]+2*cost[i]<value){value=previous[i-2]+cost[i-1]+2*cost[i];first=i==2?j:start_previous[i-2];}
                if(j>=1 && older[i-1]+last_cost[i]+2*cost[i]<value){value=older[i-1]+last_cost[i]+2*cost[i];first=i==1?j-1:start_older[i-1];}
                current[i]=value;start_current[i]=first;
            }
            const int duration=j-start_current[length]+1;
            if(j>=n-recent && duration>=min_duration && duration<=max_duration)best=std::min(best,current[length]/(length+duration));
            older=previous;start_older=start_previous;previous.swap(current);start_previous.swap(start_current);last_cost=cost;
        }
        scores[k]=best;
    }
    return 0;
}
