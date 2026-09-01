# Beyond Isolated Behaviors: Hierarchical User Modeling for LLM Personalization

Liang Wang1*,3, Xinyi Mou1*, Xiaoyou Liu1,3, Tiannan Wang3, Yuqing Wang3, Zhongyu Wei1,2†

1School of Data Science, Fudan University

2Shanghai Innovation Institute

3OPPO

liangwang25,xiaoyouliu25@m.fudan.edu.cn, xymou20,zywei@fudan.edu.cn

## Abstract

Large Language Models (LLMs) have demon- strated remarkable capabilities across diverse domains, yet personalizing their outputs to individual users remains an open challenge. Existing approaches predominantly adopt a flat behavioral paradigm, aggregating user be- haviors without an explicit account of how they are organized into deeper behavioral structures. In this work, we draw on Pierre Bourdieu’s Theory of Practice to propose PHF (Practice-Habitus-Field), a sociologically grounded framework that reconceptualizes LLM personalization through three hierarchical levels: individual behaviors as practices, their temporal accumulation into stable dispositions as habitus, and shared regularities across simi- lar users as fields. We instantiate PHF through PHFCompass, a lightweight and model-agnostic implementation based on a frozen LLM. Exper- iments on the Language Model Personalization (LaMP) benchmark demonstrate consistent im- provements across diverse tasks, while further analyses validate the interpretability and exten- sibility of the learned behavioral structures.1 [URL 🔗](#page-0)

*Figure 1: Comparison of personalization paradigms. (a) Existing methods adopt a flat behavioral paradigm, retrieving or encoding user behaviors without explicit structural modeling. (b) Habitus captures the temporal accumulation of repeated behaviors into stable disposi- tions. (c) Field captures shared behavioral regularities among users with similar dispositions. (d) PHF inte- grates practice, habitus, and field into a unified hierar- chical framework for LLM personalization.*

Recent approaches to LLM personalization have explored retrieval-augmented prompting, learned user representations, and parameter-efficient adap- tation (Salemi et al., 2024; Tan et al., 2024b; Liu et al., 2025). While these methods have shown promising results, they predominantly adopt a flat behavioral paradigm that treats user behaviors as an unordered collection of observed instances, as il- lustrated in Figure. 1(a). This flat formulation gives rise to two key limitations: (1) behavior fragmen- tation: within each user, behavioral histories lack internal structure, where they are treated as isolated instances rather than being consolidated into stable long-term patterns. (2) user isolation: users are modeled independently, without leveraging shared behavioral regularities across users with similar behavioral profiles, limiting generalization when user history is sparse. Together, these limitations make it difficult to capture the multi-level behav- ioral structures that govern user behavior, leading to suboptimal personalization. [URL 🔗](#page-0)

## 1 Introduction

Large language models (LLMs) have demonstrated remarkable capabilities across diverse tasks and domains, driving growing interest in personalized language generation (He et al., 2025; Deng et al., 2023; Ning et al., 2025; Hebert et al., 2024; Deng et al., 2025; Li et al., 2024; Bao et al., 2024). In personalized settings, user expectations are inher- ently heterogeneous: responses appropriate for one user may not align with the expectations of another. Consequently, effective personalization requires models to capture the underlying behavioral pat- terns that shape user preferences and behaviors. [URL 🔗](#page-0)


Addressing these limitations requires a struc- tured view of user behavior, modeling both how behaviors consolidate within individuals and how behavioral regularities are shared across users. We draw inspiration from Pierre Bourdieu’s Theory of Practice (Bourdieu, 1990, 2018, 2020), a well- established sociological framework that organizes human behavior around repeated actions, durable dispositions, and shared social spaces. Based on this perspective, we propose PHF (Practice- Habitus-Field), a hierarchical user modeling frame- work that addresses both limitations through a uni- fied multi-level representation. In PHF, individual behaviors are first abstracted as practices, which progressively consolidate into habitus, stable be- havioral dispositions that capture the long-term ten- dencies within each user (Figure. 1(b)). Users with similar habitus are further organized into shared fields, which encode collective behavioral regular- ities (Figure. 1(c)). Collectively, PHF formulates LLM personalization as a hierarchical behavioral modeling problem (Figure. 1(d)) that jointly cap- tures within-user disposition formation and cross- user behavioral structure. [URL 🔗](#page-0)

To implement PHF, we develop PHFCompass (COmbined Modeling of Practice, Accumulated Structure, and Shared signals), a lightweight model compatible with diverse backbones. PHFCompass represents practices by mapping individual behav- iors into discrete semantic prototypes, filtering surface-level noise while preserving core behav- ioral semantics. These practices are then tem- porally aggregated into habitus representations that encode stable long-term behavioral disposi- tions for each user. To capture collective struc- ture, PHFCompass further organizes users into latent fields derived from their habitus, enabling users with similar dispositions to benefit from shared be- havioral regularities. During inference, both habi- tus and field representations are provided to the LLM. This enables personalized generation that re- flects both individualized dispositions and broader collective patterns. Our main contributions are sum- marized as follows:

(1) We propose PHF (Practice-Habitus-Field), a sociologically grounded framework for LLM per- sonalization that draws on Bourdieu’s Theory of Practice. PHF introduces a hierarchical behavioral structure comprising practice, habitus, and field, providing a unified perspective that captures both the temporal coherence within individual behav- ior and the shared regularities across behaviorally

similar users.

- (2) We develop PHFCompass, a concrete instan- tiation of PHF that operationalizes the three con- structs through residual behavioral abstraction, tem- poral aggregation, and collaborative clustering. PHFCompass is lightweight, model-agnostic, and requires no modification to the underlying LLM.

- (3) Extensive experiments on the Language Model Personalization (LaMP) benchmark demon- strate that ments across both classification and generation tasks. Further analyses validate the interpretability of the learned behavioral structures and support the utility of the proposed sociological perspective. PHFCompass achieves consistent improve-

## 2 Related Work

## 2.1 LLM-based Personalization

Despite strong general capabilities in reasoning, knowledge-intensive tasks, and domain applica- tions (Joshi et al., 2017; Liang et al., 2025; Wu et al., 2025; Jia et al., 2025), LLMs remain fun- damentally limited in personalization. Since stan- dard LLMs are trained on broadly aggregated cor- pora, they capture general linguistic and task pat- terns but contain limited information about individ- ual behavioral tendencies, preferences, and long- term decision logic (Tao et al., 2025; Xi et al., 2025). Existing LLM personalization methods can be broadly characterized by how they utilize user behavioral histories. Retrieval-based meth- ods personalize generation by selecting relevant be- haviors from user history and incorporating them into prompts (Salemi et al., 2023; Kumar et al., 2024; Shi et al., 2025; Zhang et al., 2024; Wang et al., 2025). While flexible, these approaches op- erate at the level of individual behaviors without aggregating them into a holistic user representa- tion. Aggregation-based methods instead construct unified user representations through summarized preferences (Zhang, 2024), learned soft prompts or PEFT modules (Zhuang et al., 2024; Zhang et al., 2025b), compressed user embeddings (Liu et al., 2025), or retrieval optimization (Salemi et al., 2024). These methods merge behavioral signals into user-level representations but do so without explicitly modeling how behaviors are internally organized or how regularities are shared across users. In both cases, user behavior is treated as a flat collection of observed instances, leaving the within-user behavioral structure and cross-user be- havioral regularity largely unaddressed. [URL 🔗](#page-0)


*Figure 2: Overview of the PHF framework and PHFCompass implement. (1) Raw behaviors are abstracted into denoised practice essence via semantic ID extraction. (2) Practices are temporally aggregated into stable habitus representations. (3) Users are organized into latent fields through group router. (4) Habitus and field embeddings are combined as well as the query embedding to condition the LLM for personalized generation.*

## 2.2 User Embedding Modeling

Learning user representations from behavioral data has long been central to personalized sys- tems (Elkahky et al., 2015; Purificato et al., 2024; Ko et al., 2022; Mu, 2018). Recent LLM per- sonalization methods further model users through textual profiles, behavioral summaries, or train- able embeddings derived from interaction histo- ries (Hebert et al., 2024; Doddapaneni et al., 2024; Liu et al., 2025). Temporal weighting and semantic quantization techniques have also been introduced to better capture salient behavioral signals (Zare, 2025; Dai et al., 2022; Rajput et al., 2023; Zheng et al., 2024; Deng et al., 2025; Chen et al., 2025). CURP (Annoymous, 2026) models users with both a stable inner representation and a query-aware dy- namic representation via PQ quantization, balanc- ing the effectiveness and efficiency. Different from prior work that primarily models behaviors inde- pendently, our approach organizes user behaviors into hierarchical behavioral structures, capturing both stable individual dispositions and collective regularities across users. [URL 🔗](#page-0)

## 3 Method

## 3.1 PHF Framework Setup

We introduce PHF, a hierarchical user modeling framework for LLM personalization, illustrated in

the left part of Figure. 2. PHF organizes personal- ization through three behavioral levels: practice, habitus, and field. Individual user behaviors are first treated as practices, which are progressively accumulated into habitus, stable behavioral dis- positions that characterize each user’s long-term tendencies. Users with similar habitus are further organized into shared fields that capture collective behavioral regularities across behaviorally similar users. Personalized generation is conditioned on both habitus and field representations, yielding the following task formulation: [URL 🔗](#page-0)

Let U = {u1, u2, . . . , uN} denote a set of N users. Each user ui is associated with a chronologically ordered interaction history Hi = {hi1, hi2, . . . , hiTi}, where each hit = (qit, rit) is a query-response pair. Given a new query Qi, the goal is to generate a personalized response con- ditioned on the user’s behavioral history: P(Ri | Qi,Hi). Following the PHF hierarchy, each inter- action is abstracted into a practice representation, temporally aggregated into a habitus embedding hi, and associated with a field embedding fi. Per- sonalized generation is thus conditioned on both individual and collective signals:


## 3.2 PHFCompass Architecture

To instantiate the PHF framework, we develop PHFCompass, a lightweight and model-agnostic ar- chitecture that operationalizes the three levels of PHF through dedicated model components. The ar- chitecture is shown in the right part of Figure. 2 and training consists of two stages. In the first stage, we train the model to learn improved practice rep- resentations. In the second stage, these optimized representations are used to further construct habi- tus and field, which are then jointly leveraged for personalized generation. [URL 🔗](#page-0)

Enhanced Practice: Denoised Behavior Essence As illustrated in Figure. 2-(1), raw user behavior- soften contain substantial surface variation. Di- rectly modeling continuous embeddings risks over- fitting to contextual details rather than capturing stable behavioral semantics. To obtain more robust representations, we follow recent semantic quanti- zation approaches (Deng et al., 2025; Chen et al., 2025) and abstract each interaction into a discrete semantic prototype (Annoymous, 2026). This dis- cretization serves as a behavioral abstraction pro- cess: behaviors with different surface forms but similar underlying intent converge toward shared prototypes. [URL 🔗](#page-0)

Given an interaction hit, we first encode it into a dense representation:

where Enc(·) denotes a lightweight encoder. De- tailed implementation choices are deferred to the Appendix D. [URL 🔗](#page-0)

We then apply multi-level residual vector quanti- zation to progressively decompose each interaction into coarse-to-fine semantic components:

where r0 = xit and Cl denotes the codebook at the l-th quantization level. Higher levels capture dominant behavioral intent, while lower levels pro- gressively refine finer-grained distinctions. The final practice representation is reconstructed as:

where (i1, . . . , iL) denotes the hierarchical Seman- tic ID of the interaction.

The quantization module is optimized through

LRQ, a combination of reconstruction, commit- ment, and codebook regularization objectives:

The first term minimizes reconstruction error be- tween the original and quantized representations. The second and third terms are symmetric com- mitment losses that encourage the encoder outputs

and codebook entries to converge, where sg(·) de- notes the stop-gradient operator. The final term is a codebook utilization regularizer that penalizes de- viation of the codeword usage distribution ¯pl from

the uniform distribution U, preventing codebook collapse. Following prior work (Deng et al., 2025; Chen et al., 2025), the codebooks are initialized through balanced K-Means and are maintained as task-specific. Additional implementation details are provided in the Appendix E. [URL 🔗](#page-0)

Habitus: Modeling Long-Term Behavioral Dis- positions As illustrated in Figure. 2-(2), to model the stable behavioral dispositions formed through repeated behaviors, we aggregate the sequence of [URL 🔗](#page-0)

denoised practice representations

{ˆxit}Ti

t=1 for user

ui over time with a time fusioner. Since more recent behaviors tend to better reflect a user’s cur- rent preferences, we simplify this as a temporally weighted aggregation:

The square-root scaling ensures that the recency effect grows sublinearly, preventing recent behav- iors from dominating the representation while still preserving temporal sensitivity. The resulting habi- tus vector hi encodes a coherent representation of the user’s long-term behavioral disposition, which subsequently serves as the basis for modeling col- lective behavioral structure in the field.

Field: Collective Behavioral Structure As illus- trated in Figure. 2-(3), to capture shared behavioral regularities across users, we organize users into latent fields through a group router based on their habitus representations. The underlying intuition is [URL 🔗](#page-0)


that users with similar long-term behavioral dispo- sitions tend to exhibit similar preferences, suggest- ing that shared behaviorals can complement purely individual modeling. This idea is related in spirit to collaborative filtering (Shi et al., 2025), where similar users provide useful inductive bias for one another. However, unlike classical collaborative filtering, personalization datasets typically lack suf- ficient overlapping observations across identical items or contexts. We therefore approximate this shared structure by inducing latent fields through clustering over user-level habitus representations. [URL 🔗](#page-0)

Specifically, we induce latent fields by partition- ing users with their habitus via K-Means:

where each centroid µk corresponds to a field em- bedding that encodes the shared behavioral dispo- sition of users within that cluster. Each user is then assigned to the nearest field:

The resulting field representations capture collec- tive behavioral regularities across users with simi- lar long-term dispositions, providing complemen- tary signals that are particularly informative under sparse-history and cold-start settings.

## 3.3 Generation with Hierarchical User Representation

Finally, as shown in Figure. 2-(4), we condition the downstream LLM on both habitus and field representations. Specifically, we project them into the LLM embedding space: [URL 🔗](#page-0)

The final input sequence is constructed as:

The model is optimized using the standard lan- guage modeling objective:

Only lightweight projection layers are trained, while the underlying LLM remains frozen. This design enables scalable personalization grounded

in both individual behavioral dispositions and col- lective social structure. During inference, each user is assigned to the nearest field based on cluster cen- troids learned during training, requiring no access to other users’ data.

## 4 Experiments

## 4.1 Experiment Setup

## 4.1.1 Dataset

We conduct experiments on the Language Model Personalization (LaMP) benchmark (Salemi et al., 2023). Following prior work (Liu et al., 2025; Shi et al., 2025; Tan et al., 2024b,a; Zhang et al., 2025a), we evaluate our framework on all six pub- lic tasks2. The selected tasks span both 3 classi- fication tasks and 3 generation tasks. The clas- sification tasks contain: (1) LaMP-1: Personal- ized Citation Identification; (2) LaMP-2: Person- alized Movie Tagging; (3) LaMP-3: Personalized Product Rating; The generation tasks contain: (4) LaMP-4: Personalized News Headline Genera- tion; (5) LaMP-5: Personalized Scholarly Title Generation; and (6) LaMP-7: Personalized Tweet Paraphrasing. Since the test sets are held out by the benchmark organizers, we report results on the of- ficial validation sets using the provided time-based splits. More details are provided in Appendix A. [URL 🔗](#page-0)

## 4.1.2 Evaluation Metrics

Following the default evaluation protocol of the LaMP benchmark, we adopt task-specific met- rics as follows: Accuracy for LaMP-1; Accuracy and F1-score for LaMP-2; Mean Absolute Error (MAE) and Root Mean Squared Error (RMSE) for LaMP-3; and ROUGE-1 (R-1), ROUGE-L

(R-L)

for LaMP-4, LaMP-5, and LaMP-7.

## 4.2 Implementation Details

We use Contriever

default encoder and Qwen2.5-7B-Instruct (Team, 2024) as the decoder. For residual quantization codebooks, we use L = 3 layers with codebook sizes of 32, 32, and 16. The default number of retrieved histories is set to k = 8, and the number of field clusters is set to K = 10. We optimize the model using AdamW with a learning rate of [URL 🔗](#page-0)

1

NVIDIA A100 (80GB) GPUs. Additional details are provided in the Appendix G. [URL 🔗](#page-0)

(Izacard et al., 2021) [URL 🔗](#page-0)

as the

× 10−4. All experiments are conducted on 8


| Task Metric | Zero | Flat: Retrieval-Based |   | Flat: Aggregation-Based |   |   | PHF Implements |   |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|   | Shot | Recency BM25 Dense ROPG OPPU DiffMean PPlug T-H T-F L-F T-H+T-F T-H+L-F |   |   |   |   |   | PHFCompass |
| LaMP-1 Acc↑ | 0.464 | 0.504 0.504 0.529 0.526 | - | - | 0.520 | 0.488 0.487 0.535 0.525 | 0.569 | 0.631 |
| Acc↑ LaMP-2 | 0.366 | 0.449 0.453 0.490 0.489 |   |   | 0.444 0.374 0.503 | 0.457 0.467 0.528 0.518 | 0.506 | 0.531 |
| F1↑ | 0.337 | 0.432 0.437 0.468 0.455 |   |   | 0.400 0.343 0.448 | 0.478 0.444 0.433 0.490 | 0.474 | 0.461 |
| MAE↓ LaMP-3 | 0.498 | 0.456 0.495 0.414 0.483 |   |   | 0.426 0.504 0.314 | 0.355 0.367 0.419 0.324 | 0.334 | 0.260 |
| RMSE↓ | 0.825 | 0.811 0.859 0.750 0.840 |   |   | 0.740 0.834 0.805 | 0.691 0.725 0.762 0.660 | 0.655 | 0.579 |
| R-1↑ LaMP-4 | 0.145 | 0.167 0.170 0.171 0.165 | 0.192 |   | 0.146 0.182 | 0.168 0.152 0.168 0.158 | 0.174 | 0.193 |
| R-L↑ | 0.123 | 0.150 0.151 0.153 0.148 | 0.170 |   | 0.126 0.162 | 0.151 0.136 0.151 0.140 | 0.155 | 0.172 |
| R-1↑ LaMP-5 | 0.441 | 0.461 0.463 0.465 0.461 |   |   | 0.475 0.442 0.512 | 0.471 0.476 0.476 0.485 | 0.489 | 0.516 |
| R-L↑ | 0.360 | 0.387 0.389 0.391 0.385 |   |   | 0.398 0.358 0.443 | 0.392 0.398 0.403 0.411 | 0.412 | 0.453 |
| R-1↑ LaMP-7 | 0.448 | 0.418 0.464 0.462 0.447 | - |   | 0.444 0.524 | 0.456 0.414 0.463 0.418 | 0.459 | 0.535 |
| R-L↑ | 0.392 | 0.365 0.408 0.406 0.393 | - |   | 0.388 0.465 | 0.400 0.365 0.406 0.369 | 0.403 | 0.475 |

*Table 1: Performance of all methods on the LaMP benchmark. Existing personalization methods are organized under the flat paradigm, while PHF Implements validate each level of the proposed hierarchy. The best results are shown in bold, and the second-best are underlined. ↑ indicates that higher values are better. “–” denotes that the method is not applicable. All metrics are the average of 3 independent reruns with different random seeds.*

## 4.3 Baselines

We compare PHFCompass against representative per- sonalization methods organized in 3 categories, along with alternative implements of PHF.

Zero-Shot: The base Qwen2.5-7B-Instruct model generates responses solely from the input query without incorporating any user information.

Flat: Retrieval-Based:

alize by selecting individual behaviors from user history without aggregating them into a unified representation. (1) Recency retrieves the most recent k behaviors according to temporal order. (2) BM25 (Robertson and Zaragoza, 2009) re- trieves query-relevant histories using sparse lex- ical matching. (3) Dense (Izacard et al., 2021) uses dense semantic embeddings for retrieval. (4) ROPG (Salemi et al., 2024) further improves dense retrieval through reinforcement learning optimiza- tion of the retriever. [URL 🔗](#page-0)

Flat Aggregation-Based: These methods con- struct a unified user representation by aggregating behaviors, but without explicitly modeling how behaviors are structured. (1) OPPU (Tan et al., 2024b) trains dedicated LoRA (Hu et al., 2022) adapters for each user. (2) DiffMean (Zhang et al., 2025a) models user style through residual acti- vation differences between personalized and non- personalized responses. (3) PPlug (Liu et al., 2025) aggregates historical interaction embeddings into a unified query-aware user representation. [URL 🔗](#page-0)

PHF Variants: To validate each level of the PHF hierarchy, we implement variants that operational- ize habitus and field through different mechanisms. (1) T-H (Zhang, 2024) constructs habitus by sum- marizing user histories into textual persona descrip- tions using Qwen2.5-14B-Instruct.(2) T-F con- structs field similar with T-H to summarize collec- tive preferences and behavioral tendencies within [URL 🔗](#page-0)

These methods person-

each user group. (3) L-F (Shi et al., 2025) con- structs field through cross-user retrieval over be- havior pools from similar users. (4) T-H+T-F com- bines textual habitus summaries with text-based field descriptions. (5) T-H+L-F combines textual habitus summaries with cross-user retrieval-based field modeling. [URL 🔗](#page-0)

## 4.4 Main Results

The experimental results on the validation set are shown in Table 1, and we can observe that: [URL 🔗](#page-0)

(1) PHFCompass consistently achieves the best performance across all tasks, yielding sub- stantial improvements over the strongest flat- paradigm baselines on classification tasks and consistent gains on generation tasks. Among other methods, retrieval-based approaches benefit from semantic matching (e.g., BM25 and Dense consistently outperform Recency and Zero-Shot), but remain limited by their reliance on individual behaviors. Aggregation-based methods such as PPlug and OPPU achieve stronger results by con- structing holistic user representations, yet still un- derperform PHF variants. This suggests that while behavioral aggregation is beneficial, explicitly mod- eling the structure of user behavior is crucial for capturing the multi-level regularities that drive ef- fective personalization.

(2) Habitus and filed are complementary, and jointly modeling both yields stronger perfor- mance than modeling either level alone. The results show that either level alone improves over flat baselines (e.g., T-H and T-F perform better than some flat paradigms on most tasks), and combining both yields further gains. Comparing different PHF implements, we can further find that PHFCompass achieves strongest results overall, confirming our dedicated behavioral modeling outperforms text- based alternatives like T-H+T-F and T-H+L-F.


| Method | LaMP-1 | LaMP-2 | LaMP-3 | LaMP-4 | LaMP-5 | LaMP-7 |
| --- | --- | --- | --- | --- | --- | --- |
|   | Acc↑ |   |   | Acc↑ F1↑ MAE↓ RMSE↓ R-1↑ R-L↑ R-1↑ R-L↑ R-1↑ R-L↑ |   |   |
| PHFCompass | 0.631 | 0.531 0.461 | 0.260 0.579 |   | 0.193 0.172 0.516 0.453 0.525 0.465 |   |
| w/o Habitus | 0.501 | 0.401 0.349 | 0.321 0.649 |   | 0.178 0.157 0.490 0.425 0.491 0.431 |   |
| w/o Field | 0.598 | 0.527 0.435 | 0.264 0.588 |   | 0.199 0.176 0.517 0.453 0.529 0.467 |   |
| w/o Temporal | 0.503 | 0.538 0.471 | 0.265 0.584 |   | 0.201 0.180 0.519 0.454 0.518 0.460 |   |
| w/o Codebook | 0.496 | 0.508 0.428 | 0.293 0.594 |   | 0.156 0.138 0.458 0.381 0.500 0.439 |   |

*Table 2: Ablation study of PHFCompass on the LaMP benchmark. “w/o” denotes removing the corresponding component from PHFCompass. “w/o Temporal” replaces temporally weighted aggregation with simple averaging, and “w/o Codebook” removes residual quantization and use original embedding.*

| Encoder + | LaMP-2 | LaMP-4 |
| --- | --- | --- |
| Decoder | Acc F1 | R-1 R-L |
|   | Contriever+Qwen 0.531 0.461 0.199 0.176 |   |
|   | Contriever+LLaMA 0.510 0.423 0.215 0.193 |   |
|   | RoBERTa+Qwen 0.523 0.451 0.198 0.177 |   |
|   | RoBERTa+LLaMA 0.533 0.437 0.213 0.191 |   |

*Table 3: Overall performance of models with different encoders and decoders on LaMP-2 and LaMP-4.*

## (3) Different tasks benefit from different levels of the PHF hierarchy, highlighting the distinct roles of habitus and field in personalization..

Classification tasks (LaMP-1 to 3) primarily de- pend on user behavioral logic, so field modeling is particularly beneficial by compensating for sparse individual histories. As a result, field-enchanced methods like T-H, T-H+T-F and PHFCompass ob- viously lead the classification tasks. In contrast, generation tasks rely on content stylistic consis- tency, so training-based aggregation methods like OPPU and PPlug remain competitive. PHFCompass, benefiting from the robust modeling of practice and habitus (see Sec. 4.5), also show prominent performance on these tasks. Overall, PHFCompass achieves the strongest performance across both task types, demonstrating the advantage of modeling multiple levels of user behavior. [URL 🔗](#page-0)

## 4.5 Ablation Study

We conduct an ablation study to evaluate the con- tribution of each component in PHFCompass. As shown in Table 2, we analyze the model from two perspectives: [URL 🔗](#page-0)

The effect of PHF constructs. Removing habi- tus (w/o Habitus) causes the largest performance degradation across all tasks, confirming that fine- grained individual behavioral representations are fundamental to effective personalization. Remov- ing field (w/o Field) leads to more moderate de- clines, particularly on classification tasks, indicat- ing that collaborative signals are especially benefi- cial when behavioral reasoning rather than stylistic variation drives personalization. These results show

*(a) Performance of different field number on LaMP-2*

*(b) The t-SNE visualization of user cluster fields.*

*Figure 3: The influence of field granularity.*

## that both habitus and field contribute meaning- fully to personalization, with habitus playing the dominant role.

The effect of implementation choices of PHFCompass. Replacing temporal weighting (w/o Temporal) with uniform averaging mainly affects tasks involving evolving user preferences, suggest- ing that temporal aggregation provides complemen- tary gains beyond habitus construction itself. In ad- dition, removing residual quantization (w/o Code- book) consistently degrades performance across all tasks, with especially large drops on genera- tion benchmarks. This highlights the importance of behavioral abstraction: without discrete prac- tice representations, surface-level noise propagates through the entire hierarchy. Therefore, the effec- tiveness of PHF also depends on our implemen- tation choices.

## 4.6 Further Analysis

We further conduct additional analysis on LaMP-2 (classification) and LaMP-4 (generation).

## 4.6.1 Impact of Field Granularity

A key design choice in PHF is the granularity of the field, which determines how finely the user pop- ulation is partitioned into behavioral communities. This granularity is controlled by the number of clus- ters K: a smaller K yields coarser fields that group diverse users together, potentially diluting shared behavioral signals with outlier patterns; a larger K produces finer fields with higher internal homo- geneity but fewer users per cluster, weakening the


*Figure 4: Impact of codebook configuration. The no- tation a-b-c indicates the codebook size for each layer. “All KMeans” applies standard K-Means initialization for all three layers.*

collaborative signal due to data sparsity. This trade- off is evident in Figure. 3a: performance improves as K increases from small values, but begins to decline once the fields become overly fragmented. The best balance is achieved at K = 10, where both metrics are jointly optimized. Figure. 3b fur- ther illustrates the corresponding t-SNE visualiza- tion of user habitus, showing that the induced fields are well separated and internally cohesive. [URL 🔗](#page-0)

## 4.6.2 Model-Agnostic Extensibility

To validate the generalizability of PHFCompass across different model architectures, we replace the default Contriever encoder and Qwen2.5-7B- Instruct decoder with RoBERTa-large (Liu et al., 2019) and LLaMA-3-8B-Instruct (Grattafiori et al., 2024), respectively. As shown in Table 3, PHFCompass maintains strong performance across all four encoder-decoder combinations, with only minor variation across configurations. This robust- ness demonstrates that the PHF framework is not tied to any specific backbone architecture. We fur- ther observe that LLaMA performs better on gen- eration tasks, while Qwen achieves comparable or stronger results on classification tasks, suggest- ing that although backbone choice influences task preference, the effectiveness of PHF remains con- sistent across architectures. [URL 🔗](#page-0)

## 4.6.3 Impact of Codebook Configuration

The codebook size directly determines the num- ber of discrete practice categories and therefore the expressive capacity of user behavior modeling. To analyze this impact, we conduct experiments using different codebook size. As shown in Fig- ure. 4(a), a small codebook fails to capture suffi- cient behavioral diversity, limiting personalization, while an excessively large codebook leads to sparse codeword usage and degraded performance due to under-trained entries. Furthermore, we analyze dif- ferent initialization strategy (Figure. 4(b)). We find that the first two quantization layers primarily [URL 🔗](#page-0)

capture dominant behavioral patterns, for which standard K-Means provides a better fit than enforc- ing uniform code usage through balanced K-Means. In contrast, the third residual layer models small- magnitude residual signals and is more prone to code collapse under standard K-Means. This re- sults in the final 32-32-16 configuration with a hy- brid initialization strategy: standard K-Means for the first two layers and balanced K-Means for the third. This achieves both high behavioral coverage and stable code utilization.

## 4.6.4 Interpretability of PHFCompass

PHFCompass uses RQ-VAE to extract both shared patterns and personalized signals in a highly in- terpretable manner: (1) movies in user behavior histories with same semantic ID exhibit strong the- matic coherence: e.g., 0-14-2 groups romance nar- ratives set in fantastical worlds (Wonder Woman, Howl’s Moving Castle). (2) even under the same coarse tag like romance, different level-1 codes reveal fine-grained distinctions: 0- emphasizes oth- erworldly settings, while 16- focuses on identity and emotional realism (Juno, Safe Haven). (3) identical movies yield distinct IDs when paired with different tags, e.g., Inception as action gives 8-21-12, but as psychology it becomes 15-21-12, with only the level-1 code changing while deeper layers (-21-12) remain stable. These results sug- gest that the hierarchical quantization disentangles user-specific intent at the top level from shared se- mantic structure in deeper residual layers. More details are provided in Appendix C. [URL 🔗](#page-0)

## 5 Conclusion

In this work, we propose PHF (Practice–Habitus– Field), a sociologically inspired framework that or- ganizes LLM personalization into a unified behav- ioral hierarchy, jointly modeling within-user behav- ioral formation and cross-user behavioral regularity. Under this framework, we develop PHFCompass, a lightweight and model-agnostic implementation that abstracts user behaviors into denoised prac- tices, aggregates them into stable habitus, and sit- uates users within shared fields that capture col- lective behavioral regularities. Experiments on the LaMP benchmark demonstrate consistent im- provements across both classification and genera- tion tasks, while further analyses confirm the inter- pretability of the learned behavioral structures and the extensibility of the framework across different model architectures.


## 6 Limitations

This work has several limitations that suggest di- rections for future research.

Our experiments are conducted exclusively on the LaMP benchmark, which primarily consists of English-language text-based tasks with static user histories. The effectiveness of PHF on mul- tilingual, multimodal, or domain-specific person- alization scenarios (e.g., e-commerce, healthcare) remains to be validated. Additionally, since LaMP does not provide continuously evolving user inter- actions, we are unable to evaluate revolving habitus updates or dynamic field re-clustering in a stream- ing setting, which we consider an important direc- tion for future work.

We evaluate personalization using standard clas- sification and generation metrics such as Accuracy, F1, and ROUGE. These metrics may not fully cap- ture the nuanced aspects of personalization quality, such as user satisfaction, perceived relevance, or behavioral consistency over time.

While PHFCompass demonstrates one effective way to operationalize the PHF hierarchy, the spe- cific implementations of each level are by no means the only options. For instance, habitus could be modeled through recurrent or attention-based tem- poral architectures rather than weighted aggrega- tion, and fields could be induced through graph- based community detection or dynamic clustering rather than static K-Means. Exploring alternative implementations under the PHF framework is a promising avenue for future work.

## 7 Ethical Considerations

Personalization inherently involves modeling indi- vidual user behavior, which raises potential con- cerns regarding privacy and data usage. In this work, all experiments are conducted on the pub- licly available LaMP benchmark, which consists of anonymized user interaction data. Our frame- work operates without accessing other users’ raw data during inference — field embeddings are de- rived from cluster centroids learned during training, and no cross-user data sharing occurs at test time. Nevertheless, deploying personalization systems in real-world settings requires careful attention to user consent and data protection regulations. Addi- tionally, clustering users into shared fields based on behavioral similarity may group users in ways that reinforce existing biases in the training data. We encourage future work to investigate fairness-aware

extensions of the PHF framework and to evaluate personalization systems under broader ethical cri- teria beyond task performance.

## References

Annoymous. 2026. Curp: Codebook-based continuous user representation for personalized generation with llms. Under Review.

Zhijie Bao, Qingyun Liu, Ying Guo, Zhengqiang Ye, Jun Shen, Shirong Xie, Jiajie Peng, Xuanjing Huang, and Zhongyu Wei. 2024. Piors: Personalized intel- ligent outpatient reception based on large language model with multi-agents medical scenario simulation. arXiv preprint arXiv:2411.13902.

Pierre Bourdieu. 1990. The logic ofpractice. Stanford university press.

Pierre Bourdieu. 2018. Distinction a social critique of the judgement of taste. In Inequality, pages 287–318. Routledge.

Pierre Bourdieu. 2020. Outline of a theory of prac- tice. In The new social theory reader, pages 80–86. Routledge.

Ben Chen, Xian Guo, Siyuan Wang, Zihan Liang, Yue Lv, Yufei Ma, Xinlong Xiao, Bowen Xue, Xuxin Zhang, Ying Yang, and 1 others. 2025. Onesearch: A preliminary exploration of the unified end-to-end generative framework for e-commerce search. arXiv preprint arXiv:2509.03236.

Shaojie Dai, Yanwei Yu, Hao Fan, and Junyu Dong. 2022. Spatio-temporal representation learning with social tie for personalized poi recommendation. Data Science and Engineering, 7(1):44–56.

Jiaxin Deng, Shiyao Wang, Kuo Cai, Lejian Ren, Qigen Hu, Weifeng Ding, Qiang Luo, and Guorui Zhou. 2025. Onerec: Unifying retrieve and rank with gen- erative recommender and iterative preference align- ment. arXiv preprint arXiv:2502.18965.

Yang Deng, Wenxuan Zhang, Wai Lam, See-Kiong Ng, and Tat-Seng Chua. 2023. Plug-and-play policy planner for large language model powered dialogue agents. arXiv preprint arXiv:2311.00262.

Sumanth Doddapaneni, Krishna Sayana, Ambarish Jash, Sukhdeep Sodhi, and Dima Kuzmin. 2024. User em- bedding model for personalized language prompting. arXiv preprint arXiv:2401.04858.

Ali Mamdouh Elkahky, Yang Song, and Xiaodong He. 2015. A multi-view deep learning approach for cross domain user modeling in recommendation systems. In Proceedings ofthe 24th international conference on world wide web, pages 278–288.

Aaron Grattafiori, Abhimanyu Dubey, Abhinav Jauhri, Abhinav Pandey, Abhishek Kadian, Ahmad Al- Dahle, Aiesha Letman, Akhil Mathur, Alan Schelten,


Alex Vaughan, and 1 others. 2024. The llama 3 herd of models. arXiv e-prints, pages arXiv–2407.

Tao He, Lizi Liao, Yixin Cao, Yuanxing Liu, Yiheng Sun, Zerui Chen, Ming Liu, and Bing Qin. 2025. Simulation-free hierarchical latent policy planning for proactive dialogues. In Proceedings ofthe AAAI Conference on Artificial Intelligence.

Liam Hebert, Krishna Sayana, Ambarish Jash, Alexan- dros Karatzoglou, Sukhdeep Sodhi, Sumanth Dod- dapaneni, Yanli Cai, and Dima Kuzmin. 2024. Per- soma: Personalized soft prompt adapter architecture for personalized language prompting. arXiv preprint arXiv:2408.00960.

Edward J Hu, Yelong Shen, Phillip Wallis, Zeyuan Allen-Zhu, Yuanzhi Li, Shean Wang, Lu Wang, Weizhu Chen, and 1 others. 2022. Lora: Low-rank adaptation of large language models. ICLR, 1(2):3.

Gautier Izacard, Mathilde Caron, Lucas Hosseini, Se- bastian Riedel, Piotr Bojanowski, Armand Joulin, and Edouard Grave. 2021. Unsupervised dense in- formation retrieval with contrastive learning. arXiv preprint arXiv:2112.09118.

Zheng Jia, Shengbin Yue, Wei Chen, Siyuan Wang, Yi- dong Liu, Yun Song, and Zhongyu Wei. 2025. Ready jurist one: Benchmarking language agents for legal intelligence in dynamic environments. arXiv preprint arXiv:2507.04037.

Mandar Joshi, Eunsol Choi, Daniel S Weld, and Luke Zettlemoyer. 2017. Triviaqa: A large scale distantly supervised challenge dataset for reading comprehen- sion. arXiv preprint arXiv:1705.03551.

Hyeyoung Ko, Suyeon Lee, Yoonseo Park, and Anna Choi. 2022. A survey of recommendation systems: recommendation models, techniques, and application fields. Electronics, 11(1):141.

Ishita Kumar, Snigdha Viswanathan, Sushrita Yerra, Alireza Salemi, Ryan A Rossi, Franck Dernoncourt, Hanieh Deilamsalehy, Xiang Chen, Ruiyi Zhang, Shubham Agarwal, and 1 others. 2024. Longlamp: A benchmark for personalized long-form text genera- tion. arXiv preprint arXiv:2407.11016.

Junkai Li, Yunghwei Lai, Weitao Li, Jingyi Ren, Meng Zhang, Xinhui Kang, Siyu Wang, Peng Li, Ya-Qin Zhang, Weizhi Ma, and 1 others. 2024. Agent hospi- tal: A simulacrum of hospital with evolvable medical agents. arXiv preprint arXiv:2405.02957.

Jingcong Liang, Shijun Wan, Xuehai Wu, Yitong Li, Qianglong Chen, Duyu Tang, Siyuan Wang, and Zhongyu Wei. 2025. Hardcorelogic: Challenging large reasoning models with long-tail logic puzzle games. arXiv preprint arXiv:2510.12563.

- Jiongnan Liu, Yutao Zhu, Shuting Wang, Xiaochi Wei, Erxue Min, Yu Lu, Shuaiqiang Wang, Dawei Yin, and Zhicheng Dou. 2025. LLMs + persona-plug = personalized LLMs. In Proceedings of the 63rd

Annual Meeting ofthe Association for Computational Linguistics (Volume 1: Long Papers).

Yinhan Liu, Myle Ott, Naman Goyal, Jingfei Du, Man- dar Joshi, Danqi Chen, Omer Levy, Mike Lewis, Luke Zettlemoyer, and Veselin Stoyanov. 2019. Roberta: A robustly optimized bert pretraining ap- proach. arXiv preprint arXiv:1907.11692.

Ruihui Mu. 2018. A survey of recommender systems based on deep learning. Ieee Access, 6:69009–69022.

Lin Ning, Luyang Liu, Jiaxing Wu, Neo Wu, Devora Berlowitz, Sushant Prakash, Bradley Green, Shawn O’Banion, and Jun Xie. 2025. User-llm: Efficient llm contextualization with user embeddings. In Com- panion Proceedings ofthe ACM on Web Conference 2025, pages 1219–1223.

Erasmo Purificato, Ludovico Boratto, and Ernesto William De Luca. 2024. User model- ing and user profiling: A comprehensive survey. arXiv preprint arXiv:2402.09660.

Shashank Rajput, Nikhil Mehta, Anima Singh, Raghu- nandan Hulikal Keshavan, Trung Vu, Lukasz Heldt, Lichan Hong, Yi Tay, Vinh Tran, Jonah Samost, and 1 others. 2023. Recommender systems with generative retrieval. Advances in Neural Information Process- ing Systems, 36:10299–10315.

Stephen Robertson and Hugo Zaragoza. 2009. The probabilistic relevance framework: Bm25 and be- [URL 🔗](https://doi.org/10.1561/1500000019)

[yond.](https://doi.org/10.1561/1500000019)

Found. Trends Inf. Retr., [URL 🔗](https://doi.org/10.1561/1500000019)

3(4):333–389. [URL 🔗](https://doi.org/10.1561/1500000019)

Alireza Salemi, Surya Kallumadi, and Hamed Zamani. 2024. Optimization methods for personalizing large language models through retrieval augmentation. In Proceedings of the 47th International ACM SIGIR Conference on Research and Development in Infor- mation Retrieval, pages 752–762.

Alireza Salemi, Sheshera Mysore, Michael Bendersky, and Hamed Zamani. 2023. Lamp: When large lan- guage models meet personalization. arXiv preprint arXiv:2304.11406.

Teng Shi, Jun Xu, Xiao Zhang, Xiaoxue Zang, Kai Zheng, Yang Song, and Han Li. 2025. Retrieval augmented generation with collaborative filtering for personalized text generation. In Proceedings ofthe 48th International ACM SIGIR Conference on Re- search and Development in Information Retrieval, pages 1294–1304.

Zhaoxuan Tan, Zheyuan Liu, and Meng Jiang. 2024a. Personalized pieces: Efficient personalized large lan- guage models through collaborative efforts. In Pro- ceedings ofthe 2024 Conference on Empirical Meth- ods in Natural Language Processing.

Zhaoxuan Tan, Qingkai Zeng, Yijun Tian, Zheyuan Liu, Bing Yin, and Meng Jiang. 2024b. Democratizing large language models via personalized parameter- efficient fine-tuning. In Proceedings ofthe 2024 Con- ference on Empirical Methods in Natural Language Processing, Miami, Florida, USA.


Meiling Tao, Chenghao Zhu, Dongyi Ding, Tiannan Wang, Yuchen Eleanor Jiang, and Wangchunshu Zhou. 2025. Personafeedback: A large-scale human- annotated benchmark for personalization. arXiv preprint arXiv:2506.12915.

Qwen Team. 2024. Qwen2.5: A party of foundation models.

Piaohong Wang, Motong Tian, Jiaxian Li, Yuan Liang, Yuqing Wang, Qianben Chen, Tiannan Wang, Zhicong Lu, Jiawei Ma, Yuchen Eleanor Jiang, and 1 others. 2025. O-mem: Omni memory system for per- sonalized, long horizon, self-evolving agents. arXiv preprint arXiv:2511.13593.

Yingqian Wu, Qiushi Wang, Zefei Long, Rong Ye, Zhongtian Lu, Xianyin Zhang, Bingxuan Li, Wei Chen, Liwen Zhang, and Zhongyu Wei. 2025. Fin- team: A multi-agent collaborative intelligence sys- tem for comprehensive financial scenarios. In CCF International Conference on Natural Language Pro- cessing and Chinese Computing, pages 443–455. Springer.

Zhiheng Xi, Wenxiang Chen, Xin Guo, Wei He, Yi- wen Ding, Boyang Hong, Ming Zhang, Junzhe Wang, Senjie Jin, Enyu Zhou, and 1 others. 2025. The rise and potential of large language model based agents: A survey. Science China Information Sci- ences, 68(2):121101.

Gholamreza Zare. 2025. Tillm-rec: Temporal-interval- aware large language model for sequential recommen- dation under irregular user interactions. Available at SSRN 5453594.

Jiarui Zhang. 2024. Guided profile generation im- proves personalization with llms. arXiv preprint arXiv:2409.13093.

Jinghao Zhang, Yuting Liu, Wenjie Wang, Qiang Liu, Shu Wu, Liang Wang, and Tat-Seng Chua. 2025a. Personalized text generation with contrastive activa- tion steering. arXiv preprint arXiv:2503.05213.

Kai Zhang, Yejin Kim, and Xiaozhong Liu. 2024. Personalized llm response generation with pa- rameterized memory injection. arXiv preprint arXiv:2404.03565.

Linhai Zhang, Jialong Wu, Deyu Zhou, and Yulan He. 2025b. Proper: A progressive learning framework for personalized large language models with group-level adaptation. In Proceedings ofthe 63rd Annual Meet- ing ofthe Association for Computational Linguistics (Volume 1: Long Papers), pages 16399–16411.

Bowen Zheng, Yupeng Hou, Hongyu Lu, Yu Chen, Wayne Xin Zhao, Ming Chen, and Ji-Rong Wen. 2024. Adapting large language models by integrat- ing collaborative semantics for recommendation. In 2024 IEEE 40th International Conference on Data Engineering (ICDE), pages 1435–1448. IEEE.

Yuchen Zhuang, Haotian Sun, Yue Yu, Rushi Qiang, Qifan Wang, Chao Zhang, and Bo Dai. 2024. Hydra: Model factorization framework for black-box llm personalization. Advances in Neural Information Processing Systems, 37:100783–100815.

## A Dataset Details

Detailed statistics and example input output pair for all six tasks are provided in Table 4. We use the time-split of the benchmark. [URL 🔗](#page-0)

## B Integration with RAG

Our preliminary experiments show that retrieval- augmented generation (RAG) can provide useful personalization signals. We therefore investigate whether integrating RAG with our habitus and field embeddings further improves performance. As shown in Figure. 5, we concatenate retrieved user history with the PHF embeddings as additional con- text. Surprisingly, this integration consistently de- grades performance across tasks. We attribute this to the noise and excessive length introduced by raw retrieved text, which dilutes the focused signal from our compact latent embeddings. The effect is espe- cially pronounced in classification tasks (LaMP-2 and LaMP-3), where performance drops signifi- cantly. In contrast, generation tasks (LaMP-4 and LaMP-5) show only minor fluctuations, suggesting greater robustness to input noise. These results in- dicate that our latent habitus and field embeddings already capture essential user characteristics effec- tively, eliminating the need for redundant or noisy textual context from RAG. [URL 🔗](#page-0)

## C Interpretability

To further exhibit the interpretability of the Se- mantic ID based practice expression, we further exhibit some examples as shown in Table 5 and 7. [URL 🔗](#page-0)

## D Detailed Procedure for Encoder Refinement

Although the main framework only requires a lightweight interaction encoder, in practice we fur- ther refine the encoder to better align contextual semantics with user-specific behavioral expression. Specifically, given an interaction


| Task #Train #Dev In Len | #Cls or | Hist Len | Input Format | Output | History |
| --- | --- | --- | --- | --- | --- |
|   | Out Lens |   |   | Format | Format |
| LaMP-1 6,542 1,500 51.43 | 2 | 84.15 | For an author who has written the paper with title “{title}”, which reference | <1> | title: {title} |
|   |   |   | is related? Just answer with <1> or <2>. <1>: “{ref1}” <2>: “{ref2}” |   | abstract: {abs} |
| LaMP-2 5,073 1,410 92.39 | 15 | 86.76 | Which tag does this movie relate to among the following tags? Just | sci-fi | description: {des} |
|   |   |   | answer with the tag name. tags: [sci-fi, action, ...] description: {movie} |   | tag: {tag} |
| LaMP-3 20,000 2,500 128.18 | 5 | 185.40 | What is the score of the following review on a | 3 | text: {review} |
|   |   |   | scale of 1 to 5? Just answer with 1–5. review: {review} |   | score: {score} |
| LaMP-4 12,500 1,500 29.97 | 10.07 | 204.59 | Generate a headline for the following article: {article} | How I Got ’Rich’ | title: {title} |
|   |   |   |   |   | text: {article} |
| LaMP-5 14,682 1,500 162.34 9.71 |   | 87.88 | Generate a title for the following abstract of a paper: {abstract} | Distributed Partial | title: {title} |
|   |   |   |   | Clustering | text: {abstract} |
| LaMP-7 13,437 1,498 29.72 | 16.96 | 15.71 | Paraphrase the following tweet without any explanation: {tweet} | gotta make the most of | text: {tweet} |
|   |   |   |   | my last full day in ktown |   |

*Table 4: Dataset statistics and input–output formats for different tasks in the LaMP benchmark. “#” denotes the number of instances, “Cls” indicates classification tasks, and placeholders in braces {} are replaced with dataset-specific values.*

*Table 5: Representative movies and their corresponding semantic IDs on LaMP-2*

| Semantic ID Genre Movie (Title + Summary) |   |   |
| --- | --- | --- |
| 7-10-1 | fantasy | Avengers: Infinity War – Heroes unite to stop Thanos from collecting the six Infinity Stones and |
|   |   | imposing his will on reality. |
| 7-10-1 | fantasy | The Lord ofthe Rings – Aragorn defends Gondor while Frodo and Sam journey toward Mount |
|   |   | Doom to destroy the One Ring. |
| 8-10-1 | action | Avengers: Endgame – The remaining Avengers assemble one last time to reverse Thanos’ snap and |
|   |   | restore the universe. |
| 8-10-1 | action | Iron Man 2 – Tony Stark battles government pressure, rival inventors, and his own failing health as |
|   |   | Iron Man. |
| 7-18-3 | fantasy | Harry Potter series – A young wizard uncovers secrets about his parents and battles dark forces |
|   |   | throughout his school years. |
| 7-18-3 | fantasy | Star Wars: The Last Jedi – Rey seeks training from a reluctant Luke Skywalker as the Resistance |
|   |   | prepares for its final stand. |
| 0-14-2 | romance | Wonder Woman – An Amazon princess leaves her island to fight in World War I and discover the |
|   |   | power of love and truth. |
| 0-14-2 | romance | Howl’s Moving Castle – A cursed girl finds refuge and romance in a wizard’s enchanted, walking |
|   |   | castle. |
| 16-14-2 | romance | Juno – A sharp-witted teenager navigates an unexpected pregnancy and makes an unconventional |
|   |   | choice about her future. |
| 16-14-2 | romance | Safe Haven – A mysterious woman hiding from her past finds healing and love in a small coastal |
|   |   | town. |

*Table 6: Semantic ID example for some combinations.*

| Movie (Title + Summary) | Tag | Semantic ID |
| --- | --- | --- |
| Inception – A thief who steals secrets | action | 8-21-12 |
| from dreams is hired to implant an | sci-fi | 5-21-12 |
| idea into a target’s subconscious. | twist ending 12-21-12 |   |
| Interstellar – Explorers use a | action | 26-26-7 |
| wormhole to travel across galaxies and | dystopia | 14-26-7 |
| save humanity from extinction. | twist ending 12-26-7 |   |
| The Dark Knight – Batman battles the | action | 21-25-13 |
| Joker, a criminal who tests the moral | dystopia | 14-25-13 |
| limits of Gotham’s heroes. | violence | 20-25-13 |

*Table 7: Same movie paired with diverse user tags on LaMP-2*

we separately encode the query and response:

*Figure 5: Performance comparison across LaMP-2 to 5. Each subfigure shows scores for PHF and PHF+RAG variants.*

The final interaction embedding is constructed


## Algorithm 1 Encoder Refinement with Contrastive Alignment

- 1: for each interaction hit = (qit, rit) do

- 2: Encode query embedding qit

- 3: Encode response embedding rit

4: Construct fused representation x(2)

it

- 5: Encode concatenated interaction x(1) it

6: Compute contrastive alignment loss

7: Update encoder parameters

8: end for

9: return Refined encoder Enc(·)

through weighted fusion:

where α and β balance contextual information and user-specific expression.

To further improve semantic consistency, we in- troduce a contrastive alignment objective between two complementary semantic views. The first view directly encodes the concatenated interaction:

while the second view corresponds to the weighted fusion representation:

We treat the two representations as a positive

pair and optimize a symmetric InfoNCE objective:

## Require: Interaction set H

where sim(·, ·) denotes cosine similarity, τ is a tem- perature parameter, and H denotes cross-entropy loss.

This refinement objective encourages the fused representation to preserve the joint semantics cap- tured by direct interaction encoding while main- taining a disentangled representation of contextual grounding and user-specific behavioral expression.

## E Detailed Procedure for Balanced K-Means Initialization

## Algorithm 2 Balanced K-Means Initialization

Require: Residual set R, number of clusters K

- 1: Initialize centroids {µk}K k=1

- 2: repeat

- 3: Assign residuals to nearest centroids under balance constraints

- 4: Update centroids using assigned residuals

- 5: until cluster assignments converge

- 6: return Balanced codebook centroids {µk}K k=1

*(a) Mean similarity of differ- ent encoding methods.*

*(b) Performance with and without CL on LaMP-2.*

Figure 6: The impact of contrastive learning on the encoder.

To improve codebook stability during residual quantization, especially in deeper quantization lay- ers where residual magnitudes become progres- sively smaller, we initialize the final codebook us- ing balanced K-Means.

Given residual representations

balanced K-Means aims to partition residuals into K approximately balanced clusters:

subject to:

Here, µk denotes the centroid of cluster

Ck.

Compared with standard K-Means, balanced clus- tering prevents excessive concentration of residuals into a small number of centroids, thereby improv- ing codebook utilization and stabilizing subsequent quantization training.

In practice, we only apply balanced K-Means to initialize the deepest residual codebook, while shallower codebooks are initialized using standard K-Means.

## F Impact of Contrastive Learning on the Encoder

Contrastive learning effectively reduces the spuri- ous similarity caused by length imbalance between


query and response, and avoids the artificial simi- larity introduced by simple weighted summation. Taking LaMP-2 as an example shown in Fig 6, where the query is a long movie description and the response is only 1–2 words, we observe that directly encoding the same query with different responses yields nearly identical embeddings (sim- ilarity = 0.970), making them hard to distinguish. While weighted fusion improves separability, it in- troduces extra similarity: the same response paired with different queries shows increased similarity (from 0.597 to 0.714), which is still suboptimal. In contrast, our contrastive learning approach shown in Fig 6(a) achieves the best separation by align- ing the fused representation with its reconstructed counterpart which greatly helped the downstream RQ-VAE. Fig 6(b) further validates its effective- ness: removing contrastive learning leads to clear drop in both Accuracy and F1. [URL 🔗](#page-0)

using AdamW with a batch size of 4 per GPU and a learning rate of 1×10−4. Gradient accumulation with step size 8 is applied to simulate the target effective batch size. All experiments are conducted on 8 NVIDIA A100 (80GB) GPUs.

## H Licenses

We use publicly available datasets and models that are already licensed. Our code will be released if accepted with MIT License.

## G Implementation Details

We use Contriever (Izacard et al., 2021) as the default interaction encoder and Qwen2.5-7B- Instruct (Team, 2024) as the decoder. In the ex- tensibility experiments (Section 3), we additionally evaluate RoBERTa-large (Liu et al., 2019) as the en- coder and LLaMA-3-8B-Instruct (Grattafiori et al., 2024) as the decoder. [URL 🔗](#page-0)

The codebook consists of L = 3 layers with codebook sizes of 32, 32, and 16 for layers 1, 2, and 3, respectively. Codebooks in layers 1 and 2 are initialized using standard K-Means on the train- ing data, while layer 3 employs balanced K-Means initialization to promote uniform codeword usage. The commitment loss coefficient λv and the code- book update coefficient are both set to 0.25. The usage regularization weight λu in Equation (8) is set to 0.05. The temperature is set to 0.05. The ran- dom seed we use are 0, 1, 42. We use rouge_score package to calculate ROUGE.

The hyperparameters α and β for contrastive learning are set to 1.0 and 1.2, respectively. The default number of retrieved histories is k = 8. For field-aware user clustering, users are partitioned into K = 10 groups by default. We conduct con- trastive learning for all tasks except LaMP-1 and LaMP-7 due to data format constraints.

The MLP consists of two layers with dimensions encoder_dim → decoder_dim → decoder_dim, using GELU activations. We optimize the model
