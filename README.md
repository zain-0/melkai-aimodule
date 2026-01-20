# Lease Violation Analyzer - Model Comparison Tool

A FastAPI-based tool for comparing different AI models in analyzing lease agreements for violations of local, county, and state laws. This tool helps you benchmark various models to find the best one for your production use case based on cost, speed, accuracy, and citation quality.

## Features

- 📄 **PDF Lease Parsing**: Automatically extract key information from lease documents
- 🔍 **Web Search Integration**: Search .gov websites for relevant landlord-tenant laws
- 🤖 **Multiple AI Models**: Compare models from Anthropic, OpenAI, Google, Meta, and Perplexity
- 📊 **Comprehensive Metrics**: Track cost, time, citations, and accuracy for each model
- 🎯 **Citation Verification**: Prioritize .gov sources and track law references
- ⚡ **Parallel Processing**: Run multiple model analyses simultaneously
- � **Maintenance Workflow**: NEW! Evaluate maintenance requests and generate tenant messages + vendor work orders
- �📖 **Interactive API Docs**: Built-in Swagger UI for easy testing

## Supported Models

**Total: 27 models across 7 providers**

For detailed model comparison, pricing, and recommendations, see **[MODELS.md](MODELS.md)**.

### Models with Native Web Search
- `perplexity/llama-3.1-sonar-large-128k-online` - Perplexity's large online model
- `perplexity/llama-3.1-sonar-huge-128k-online` - Perplexity's huge online model  
- `perplexity/llama-3.1-sonar-small-128k-online` - Perplexity's small online model (fastest)

### Models with DuckDuckGo Search Integration

**Anthropic Claude:**
- `anthropic/claude-3.5-sonnet` - Best overall quality
- `anthropic/claude-3.5-haiku` - Fast and efficient
- `anthropic/claude-3-haiku` - Budget-friendly
- `anthropic/claude-3-opus` - Highest quality (expensive)

**OpenAI:**
- `openai/gpt-4o` - Latest GPT-4 optimized
- `openai/gpt-4o-mini` - Fast and affordable
- `openai/gpt-4-turbo` - High performance
- `openai/o1-mini` - Reasoning-focused

**Google:**
- `google/gemini-pro-1.5` - High quality analysis
- `google/gemini-flash-1.5` - Ultra-fast processing

**Meta Llama:**
- `meta-llama/llama-3.1-405b-instruct` - Largest Llama model
- `meta-llama/llama-3.1-70b-instruct` - Balanced performance
- `meta-llama/llama-3.1-8b-instruct` - Most cost-effective
- `meta-llama/llama-3.2-90b-vision-instruct` - With vision capabilities

**Mistral:**
- `mistralai/mistral-large` - Premium Mistral model
- `mistralai/mistral-medium` - Balanced option
- `mistralai/mistral-small` - Budget-friendly
- `mistralai/mixtral-8x7b-instruct` - Mixture of experts

**DeepSeek:**
- `deepseek/deepseek-chat` - General chat model
- `deepseek/deepseek-coder` - Code-focused (good for legal text)

**Qwen:**
- `qwen/qwen-2.5-72b-instruct` - High quality Chinese AI
- `qwen/qwen-2.5-coder-32b-instruct` - Code specialist

## Installation

### Option 1: Docker Deployment (Recommended for EC2/Production) 🐳

**Fastest way to deploy to your EC2 instance:**

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd comparision-research-melk-ai
```

2. **Set up environment variables**
```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your OpenRouter API key
# OPENROUTER_API_KEY=your_actual_key_here
```

3. **Deploy to EC2 (Windows PowerShell)**
```powershell
.\deploy.ps1
```

**That's it!** Your API will be available at: `http://18.119.209.125:8000/docs`

For detailed Docker deployment instructions, see:
- **[QUICKSTART.md](QUICKSTART.md)** - Quick deployment guide
- **[README_DEPLOYMENT.md](README_DEPLOYMENT.md)** - Comprehensive deployment documentation

**Common Commands:**
```powershell
.\deploy.ps1           # Deploy/update application
.\deploy.ps1 -Logs     # View logs
.\deploy.ps1 -Restart  # Restart application
.\deploy.ps1 -Stop     # Stop application
```

### Option 2: Local Development Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd comparision-research-melk-ai
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables**
```bash
# Copy the example env file
cp .env.example .env

# Edit .env and add your OpenRouter API key
# OPENROUTER_API_KEY=your_actual_key_here
```

4. **Get your OpenRouter API Key**
   - Sign up at https://openrouter.ai
   - Generate an API key from your dashboard
   - Add it to your `.env` file

## Usage

### Docker (Production)

```bash
# Local testing with Docker
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Local Development

```bash
# Using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or using Python
python -m app.main
```

The API will be available at `http://localhost:8000`

### Access API Documentation

Open your browser and navigate to:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## API Endpoints

### 1. List Available Models
```http
GET /models
```

Returns all available models with pricing and capabilities.

### 2. Analyze with Single Model
```http
POST /analyze/single
```

Analyze a lease with a specific model using native web search.

### 3. Compare All Models
```http
POST /analyze/compare
```

Run comprehensive benchmarking across ALL configured models (23 models).

### 4. Analyze by Provider
```http
POST /analyze/provider/{provider}
```

Analyze with all models from a specific provider (openai, anthropic, google, meta, mistral, deepseek, qwen, perplexity).

### 5. Categorized Analysis (NEW!)
```http
POST /analyze/categorized
```

**Analyze with Mistral Medium 3.1 and get violations organized by category:**
- 🏠 **Rent Increase**: Rent hikes, caps, notice requirements
- ⚖️ **Tenant & Owner Rights**: Repairs, entry, privacy, deposits, evictions
- 🤝 **Fair Housing Laws**: Discrimination, accessibility, protected classes
- 📋 **Licensing**: Property licensing, registration, permits
- 📝 **Others**: Miscellaneous violations

See [CATEGORIZED_ENDPOINT.md](CATEGORIZED_ENDPOINT.md) for detailed documentation.

### 6. DuckDuckGo Search (Optional)
```http
POST /analyze/duckduckgo
```

Analyze using DuckDuckGo search + any model (optional fallback).

### 7. List Providers
```http
GET /providers
```

Get list of all available providers with their model counts.

**Response:**
```json
[
  {
    "model_id": "anthropic/claude-3.5-sonnet",
    "name": "claude-3.5-sonnet",
    "provider": "anthropic",
    "has_native_search": false,
    "estimated_cost_per_1k_tokens": {
      "input": 3.0,
      "output": 15.0
    },
    "context_length": 200000
  }
]
```

### 2. Analyze with Single Model
```http
POST /analyze/single
```

Analyze a lease with a specific model and search strategy.

**Parameters:**
- `file` (form-data): PDF lease file
- `model_name` (form-data): Model identifier (e.g., "anthropic/claude-3.5-sonnet")
- `search_strategy` (form-data): "native_search" or "duckduckgo" (default)

**Example using curl:**
```bash
curl -X POST "http://localhost:8000/analyze/single" \
  -F "file=@lease.pdf" \
  -F "model_name=anthropic/claude-3.5-sonnet" \
  -F "search_strategy=duckduckgo"
```

**Response:**
```json
{
  "model_name": "anthropic/claude-3.5-sonnet",
  "search_strategy": "duckduckgo",
  "lease_info": {
    "address": "123 Main St",
    "city": "San Francisco",
    "state": "CA",
    "rent_amount": "$2000"
  },
  "violations": [
    {
      "violation_type": "Security Deposit Limit Exceeded",
      "description": "Security deposit exceeds state maximum",
      "severity": "high",
      "confidence_score": 0.9,
      "lease_clause": "Security deposit of $5000...",
      "citations": [
        {
          "source_url": "https://leginfo.legislature.ca.gov/...",
          "title": "California Civil Code § 1950.5",
          "relevant_text": "The landlord may not demand or receive security...",
          "law_reference": "CA Civil Code § 1950.5",
          "is_gov_site": true
        }
      ]
    }
  ],
  "metrics": {
    "model_name": "anthropic/claude-3.5-sonnet",
    "search_strategy": "duckduckgo",
    "total_time_seconds": 12.5,
    "cost_usd": 0.0234,
    "gov_citations_count": 3,
    "total_citations_count": 5,
    "violations_found": 2,
    "avg_confidence_score": 0.85,
    "has_law_references": true,
    "tokens_used": {
      "prompt": 2000,
      "completion": 800,
      "total": 2800
    }
  }
}
```

### 3. Compare All Models
```http
POST /analyze/compare
```

Run comprehensive benchmarking across ALL configured models.

**Parameters:**
- `file` (form-data): PDF lease file

**Example using curl:**
```bash
curl -X POST "http://localhost:8000/analyze/compare" \
  -F "file=@lease.pdf"
```

**Response:**
```json
{
  "lease_file_name": "lease.pdf",
  "total_models_tested": 19,
  "results": [
    {
      "model_name": "anthropic/claude-sonnet-4.5",
      "violations": [...],
      "metrics": {...}
    },
    {
      "model_name": "openai/gpt-5",
      "violations": [...],
      "metrics": {...}
    }
  ],
  "best_by_cost": "meta-llama/llama-4-scout ($0.0012)",
  "best_by_time": "anthropic/claude-3-haiku (8.5s)",
  "best_by_citations": "perplexity/sonar-pro (12 .gov citations)",
  "best_overall": "anthropic/claude-sonnet-4.5"
}
```

### 4. Analyze by Provider
```http
POST /analyze/provider/{provider}
```

Analyze with all models from a specific provider (OpenAI, Anthropic, Google, Meta, etc.)

**Path Parameters:**
- `provider`: Provider name (openai, anthropic, google, meta, mistral, deepseek, qwen, perplexity)

**Body Parameters:**
- `file` (form-data): PDF lease file

**Example using curl:**
```bash
# OpenAI models only
curl -X POST "http://localhost:8000/analyze/provider/openai" \
  -F "file=@lease.pdf"

# Anthropic models only
curl -X POST "http://localhost:8000/analyze/provider/anthropic" \
  -F "file=@lease.pdf"

# Perplexity models only
curl -X POST "http://localhost:8000/analyze/provider/perplexity" \
  -F "file=@lease.pdf"
```

**Response:** Same as `/analyze/compare` but filtered to the specified provider

**Available Providers:**
- `openai` - GPT models (GPT-5, GPT-4o, GPT-4o-mini)
- `anthropic` - Claude models (Claude Sonnet 4.5, Opus, Haiku)
- `google` - Gemini models (Gemini 2.5 Flash, Gemini 2.0 Flash)
- `meta` - Llama models (Llama 4 Scout, Llama 3.3)
- `mistral` - Mistral models (Mistral Medium 3.1, Mistral Small 3.1)
- `deepseek` - DeepSeek models (DeepSeek v3.2, DeepSeek R1)
- `qwen` - Qwen models (Qwen3 Max, Qwen2.5-Coder-Instruct)
- `perplexity` - Perplexity Sonar models (Sonar Pro, Sonar, Sonar Reasoning)

### 5. List Providers
```http
GET /providers
```

Get list of all available providers with their model counts.

**Response:**
```json
{
  "total_providers": 8,
  "providers": [
    {
      "name": "anthropic",
      "models": [
        "anthropic/claude-sonnet-4.5",
        "anthropic/claude-3-opus",
        "anthropic/claude-3-haiku"
      ],
      "count": 3
    },
    {
      "name": "openai",
      "models": [
        "openai/gpt-5",
        "openai/gpt-4o",
        "openai/gpt-4o-mini"
      ],
      "count": 3
    }
  ]
}
```

### 8. Maintenance Workflow (NEW! 🔧)
```http
POST /maintenance/workflow
```

**Complete maintenance workflow in ONE API call** - evaluates maintenance request against lease, generates professional tenant message, and creates vendor work order (if approved).

**Parameters:**
- `file` (form-data): PDF lease file
- `maintenance_request` (form-data): Description of the maintenance issue
- `landlord_notes` (form-data, optional): Additional context from landlord

**Example using curl:**
```bash
curl -X POST "http://localhost:8000/maintenance/workflow" \
  -F "file=@lease.pdf" \
  -F "maintenance_request=Heater is broken, no heat for 2 days" \
  -F "landlord_notes=Emergency - freezing temperatures outside"
```

**Response:**
```json
{
  "maintenance_request": "Heater is broken, no heat for 2 days",
  "decision": "approved",
  "decision_reasons": [
    "Lease Section 8.2 states landlord maintains heating systems",
    "Heating is essential habitability requirement"
  ],
  "lease_clauses_cited": [
    "Section 8.2: Landlord shall maintain and repair all heating systems"
  ],
  "tenant_message": "We have received your maintenance request regarding the heating system. Per Section 8.2 of the lease, we are responsible for maintaining heating systems. This is a high priority repair and we will dispatch a licensed HVAC technician immediately. Expected completion: 24-48 hours.",
  "tenant_message_tone": "approved",
  "estimated_timeline": "24-48 hours",
  "alternative_action": null,
  "vendor_work_order": {
    "work_order_title": "Emergency Heating System Repair - 123 Main St",
    "comprehensive_description": "Heating system failure at 123 Main St, Unit 4B. No heat for 2 days during freezing temperatures. Requires immediate HVAC inspection and repair. Contact: John Smith.",
    "urgency_level": "emergency"
  }
}
```

**Cost:** FREE ($0.00) - Uses Llama 3.3 free model

**See detailed documentation:** [MAINTENANCE_WORKFLOW_API.md](MAINTENANCE_WORKFLOW_API.md)

**Individual Endpoints** (for separate operations):
- `POST /maintenance/evaluate` - Evaluate request and generate tenant message only
- `POST /maintenance/vendor` - Generate vendor work order only
- `POST /tenant/rewrite` - Rewrite tenant's message to be more professional

## Understanding the Results

### Metrics Explained

- **total_time_seconds**: Time taken for analysis (including search if applicable)
- **cost_usd**: Estimated cost based on OpenRouter pricing
- **gov_citations_count**: Number of citations from .gov websites
- **total_citations_count**: Total number of citations provided
- **violations_found**: Number of potential violations detected
- **avg_confidence_score**: Average confidence (0.0-1.0) across violations
- **has_law_references**: Whether citations include specific law codes (e.g., "§ 123.45")

### Choosing the Right Model

**For Production Use:**
- **Cost-sensitive**: Use `deepseek/deepseek-chat` or `meta-llama/llama-3.1-8b-instruct`
- **Speed-critical**: Use `google/gemini-flash-1.5` or `anthropic/claude-3.5-haiku`
- **Accuracy-focused**: Use `anthropic/claude-3.5-sonnet` or `openai/gpt-4o`
- **Best web search**: Use `perplexity/llama-3.1-sonar-large-128k-online`
- **Balanced**: Use the model marked as "best_overall" in comparison results

**General Guidelines:**
- **Perplexity models**: Best for comprehensive web research with native search, but more expensive
- **Claude 3.5 Sonnet**: Best balance of accuracy and cost for complex legal analysis
- **GPT-4o**: High accuracy with good speed, moderate cost
- **Claude 3.5 Haiku / GPT-4o-mini**: Fast and cheap for simple leases
- **DeepSeek models**: Extremely cost-effective, good for high-volume processing
- **Mistral Large**: European option with strong performance
- **Llama 3.1-405B**: Open-source leader, highest quality among Llama models
- **Gemini Flash**: Fastest processing for time-sensitive applications
- **Qwen models**: Strong performance at competitive prices

## Project Structure

```
comparision-research-melk-ai/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration and settings
│   ├── models.py            # Pydantic models
│   ├── pdf_parser.py        # PDF extraction logic
│   ├── web_search.py        # DuckDuckGo search integration
│   ├── openrouter_client.py # OpenRouter API client
│   └── analyzer.py          # Main analysis orchestration
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Configuration

Edit `.env` file to customize:

```env
# Required
OPENROUTER_API_KEY=your_key_here

# Optional
MAX_FILE_SIZE_MB=10
SEARCH_RESULTS_LIMIT=10
```

## Troubleshooting

### Import Errors
If you see import errors after installation:
```bash
pip install --upgrade -r requirements.txt
```

### API Key Issues
- Verify your OpenRouter API key is correct in `.env`
- Check you have credits at https://openrouter.ai

### Search Not Working
- DuckDuckGo may rate-limit requests - add delays between searches
- Some .gov sites may be slow to respond

### Model Errors
- Some models may be unavailable or rate-limited
- Check OpenRouter status: https://openrouter.ai/status

## Advanced Usage

### Using Python Requests

```python
import requests

# Compare all models
with open('lease.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/analyze/compare',
        files={'file': f}
    )

results = response.json()

# Find cheapest model
cheapest = min(
    [r for r in results['results'] if r['metrics']],
    key=lambda x: x['metrics']['cost_usd']
)

print(f"Cheapest: {cheapest['model_name']}")
print(f"Cost: ${cheapest['metrics']['cost_usd']:.4f}")
print(f"Violations: {cheapest['metrics']['violations_found']}")
```

### Filtering Results

```python
# Get only models with .gov citations
gov_results = [
    r for r in results['results']
    if r['metrics'] and r['metrics']['gov_citations_count'] > 0
]

# Get high-confidence violations only
for result in results['results']:
    high_conf_violations = [
        v for v in result['violations']
        if v['confidence_score'] >= 0.8
    ]
```

## CI/CD Pipeline

Automated testing and deployment with GitHub Actions. See detailed guides:

- 📖 **[CI_CD_SETUP_GUIDE.md](CI_CD_SETUP_GUIDE.md)** - Complete setup instructions
- ⚡ **[CI_CD_QUICK_REFERENCE.md](CI_CD_QUICK_REFERENCE.md)** - Quick commands and troubleshooting

### Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| **CI** | Push/PR | Automated tests, linting, security scans |
| **CD** | Push to main | Deploy to production server |
| **Docker** | Releases | Build and publish Docker images |

### Quick Setup
```bash
# 1. Add GitHub secrets (AWS_ACCESS_KEY_ID, DEPLOY_HOST, etc.)
# 2. Update deployment paths in .github/workflows/cd.yml
# 3. Push to trigger workflows
git add .github/
git commit -m "Add CI/CD pipeline"
git push origin main
```

Status badges:
```markdown
![CI Tests](https://github.com/zain-0/melkai-aimodule/actions/workflows/ci.yml/badge.svg)
![Deployment](https://github.com/zain-0/melkai-aimodule/actions/workflows/cd.yml/badge.svg)
![Docker](https://github.com/zain-0/melkai-aimodule/actions/workflows/docker-publish.yml/badge.svg)
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see LICENSE file for details

## Support

For issues or questions:
- Open an issue on GitHub
- Check OpenRouter documentation: https://openrouter.ai/docs

## Roadmap

- [x] CI/CD pipeline with GitHub Actions
- [ ] Add support for more AI providers
- [ ] Implement caching for search results
- [ ] Add batch processing endpoint
- [ ] Export reports to PDF
- [ ] Add database storage for historical comparisons
- [ ] Create frontend dashboard

---

**Note**: This tool is for research and comparison purposes. Always consult with legal professionals for actual lease review.
