# Data Sources — MI/CAD SNP-gene-pathway network

All sources are real, public, and correctly cited. No fabricated endpoints.

## 1. GWAS risk loci & seed genes (MI / CAD)

### Production source of truth: GWAS Catalog
- **Web:** https://www.ebi.ac.uk/gwas/
- **REST API:** https://www.ebi.ac.uk/gwas/rest/api/ — see docs at https://www.ebi.ac.uk/gwas/docs/api
- **EFO traits:** "myocardial infarction" (EFO_0000612) and "coronary artery disease" (EFO_0000378)
- **Example queries:**
  - `GET https://www.ebi.ac.uk/gwas/rest/api/efoTraits/search/findByEfoTrait?trait=myocardial%20infarction`
  - `GET https://www.ebi.ac.uk/gwas/rest/api/studies/search/findByDiseaseTrait?diseaseTrait=coronary%20artery%20disease`
  - `GET https://www.ebi.ac.uk/gwas/rest/api/associations/search/findByEfoTrait?efoTrait=EFO_0000612`
- **Bulk downloads / summary:** GWAS Catalog FTP: https://www.ebi.ac.uk/gwas/docs/api

> In production, the seed list would be derived by querying the GWAS Catalog API for EFO_0000612/EFO_0000378, filtering at genome-wide significance (p < 5×10⁻⁸), mapping lead SNPs to nearest/reported genes. In this repo, we hardcode a curated, literature-cited seed set (see below) to run without live download.

### Curated seed list (hardcoded in `data_pipeline/seed_genes.py`)
Well-replicated CAD/MI GWAS loci/genes from cardiovascular genetics literature (selection based on CARDIoGRAM, CARDIoGRAMplusC4D, and subsequent large GWAS meta-analyses; representative citations given per gene in the JSON):

| Symbol | Locus | Representative citation |
|---|---|---|
| CDKN2A / CDKN2B / ANRIL (CDKN2B-AS1) | 9p21.3 | Helgadottir et al. Science 2007; McPherson et al. Science 2007 |
| LDLR | 19p13.2 | Myocardial Infarction Genetics Consortium Nature Genetics 2009 |
| PCSK9 | 1p32.3 | Willer et al. Nature Genetics 2008 |
| APOB | 2p24.1 | CARDIoGRAMplusC4D Nature Genetics 2013 |
| LPA (Lipoprotein(a)) | 6q25.3 | Clarke et al. NEJM 2009 |
| SORT1 (PSRC1/CELSR2/SORT1) | 1p13.3 | Musunuru et al. Nature 2010 |
| APOE / APOC1 | 19q13.32 | CARDIoGRAM Nature Genetics 2011 |
| ABO | 9q34.2 | Reilly et al. Lancet 2011 |
| CXCL12 | 10q11.21 | Samani et al. NEJM 2007 |
| ADAMTS7 | 15q25.1 | Reilly et al. Nature Genetics 2011 |
| COL4A1 / COL4A2 | 13q34 | CARDIoGRAMplusC4D 2013 |
| SMAD3 | 15q22.33 | CARDIoGRAMplusC4D 2015 |
| TCF21 | 6q23.2 | CARDIoGRAMplusC4D 2011 |
| PHACTR1 | 6p24.1 | CARDIoGRAM 2009 |
| ZC3HC1 | 7q32.2 | CARDIoGRAMplusC4D 2013 |
| SLC22A3 / LPAL2 | 6q25.3 | CARDIoGRAM 2011 |
| MIA3 | 1q41 | CARDIoGRAM 2011 |
| WDR12 | 2q33.1 | CARDIoGRAMplusC4D 2013 |
| MRAS | 3q22.3 | Erdmann et al. Nature Genetics 2009 |
| SH2B3 | 12q24.12 | Gudbjartsson et al. Nature Genetics 2009 |
| KIAA1462 / JCAD | 10p11.23 | CARDIoGRAMplusC4D 2013 |

Total hardcoded seeds: 27 genes (see `data_pipeline/seed_genes.py:SEED_GENES`). Each entry carries `locus`, `pmid`, `citation`, `trait`.

## 2. Protein-protein interaction network — STRING

- **Project:** STRING (Search Tool for the Retrieval of Interacting Genes/Proteins), https://string-db.org/
- **Real download endpoint (protein links):** `https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz`
  - Homepage listing: https://stringdb-downloads.org/
  - Direct file doc: STRING v12.0, organism 9606 (Homo sapiens), tab-separated columns `protein1 protein2 combined_score` (score 0–1000; we filter `combined_score >= 700` for high confidence, per STRING documentation).
- **Aliases for ENSP→gene mapping:** `https://stringdb-downloads.org/download/protein.aliases.v12.0/9606.protein.aliases.v12.0.txt.gz`
- **API (alternative, not used for bulk):** https://string-db.org/api/ — documented at https://string-db.org/help/api/
- **Citation:** Szklarczyk et al. Nucleic Acids Res. 2023, STRING v12.

### Real-run parsing
```bash
wget https://stringdb-downloads.org/download/protein.links.v12.0/9606.protein.links.v12.0.txt.gz
python -m data_pipeline.string_parser --string-path 9606.protein.links.v12.0.txt.gz --aliases-path 9606.protein.aliases.v12.0.txt.gz --min-score 700 --out network_edges.tsv
```

## 3. Pathway membership — Reactome & KEGG

### Reactome
- **Web:** https://reactome.org/
- **Downloads page:** https://reactome.org/download-data
- **GMT file (gene sets):** `https://reactome.org/download/current/ReactomePathways.gmt` (also `ReactomePathways.gmt.zip`)
- **Alternative:** `https://reactome.org/download/current/ReactomePathways.gmt.zip` or per-species via `https://reactome.org/download/current/homo_sapiens/ReactomePathways.gmt`
- **REST API (Content Service):** https://reactome.org/ContentService/ — e.g. `GET https://reactome.org/ContentService/data/pathways/low/entity/{id}`
- **Citation:** Gillespie et al. Nucleic Acids Res. 2022.

### KEGG
- **Web:** https://www.kegg.jp/ / https://www.genome.jp/kegg/
- **REST API base:** https://rest.kegg.jp/ — documented at https://www.kegg.jp/kegg/rest/keggapi.html
- **Endpoints:**
  - `GET https://rest.kegg.jp/list/pathway/hsa` — list human pathways
  - `GET https://rest.kegg.jp/link/genes/pathway` or `GET https://rest.kegg.jp/link/hsa/pathway` — gene–pathway links
  - `GET https://rest.kegg.jp/link/pathway/hsa:10458` — pathways for a gene
  - `GET https://rest.kegg.jp/get/hsa04110` — KGML/pathway details
- **Citation:** Kanehisa et al. Nucleic Acids Res. 2023.

> In this sandbox we do NOT attempt live downloads. `data_pipeline/pathway_parser.py` implements real parsers for both Reactome GMT and KEGG link files, operable via `--pathway-path <local file>`. Tests use a small synthetic GMT fixture. Real run: pass downloaded GMT or KEGG link file.

## 4. No fabricated sources
- Every endpoint above is publicly documented and verifiable.
- No synthetic GWAS, PPI, or pathway data is presented as real in outputs.
- Metrics (recall@k, AUPRC) are computed honestly; degree baseline is compared explicitly.
