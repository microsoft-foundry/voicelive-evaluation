"""
Dataset Quality Validator

PURPOSE:
    Content quality validation of JSONL datasets to assess appropriateness
    and relevance. Run this AFTER consistency validation passes.
    
    Use this validator to assess:
    - System prompt alignment with conversation content
    - Tool definition appropriateness (action-oriented vs conversational)
    - Question intent classification
    - Content quality metrics (length, diversity, depth)

WHEN TO USE:
    - After passing consistency validation
    - To assess dataset quality before evaluation
    - To validate prompt-conversation alignment
    - To verify tool definitions match question types
    - For quality assurance in dataset creation pipelines

VALIDATION CHECKS:
    1. System prompt relevance to conversation content
       - Domain detection and keyword matching
       - Alignment percentage calculation (default or strict mode)
    2. Tool definition appropriateness
       - Action request detection vs conversational queries
       - Tool presence validation for action-oriented questions
    3. Question intent classification
       - Action requests (need tools)
       - Instructional questions (how-to)
       - General conversation
    4. Content quality metrics
       - Question/answer length analysis
       - System prompt diversity
       - Quality scoring

COMMAND LINE USAGE:
    # Basic quality validation (permissive alignment matching)
    python validate_dataset_quality.py dataset.jsonl
    
    # Strict mode - conservative keyword-only matching (~50% vs ~88%)
    python validate_dataset_quality.py dataset.jsonl --strict
    
    # Verbose mode - detailed per-conversation analysis
    python validate_dataset_quality.py dataset.jsonl --verbose
    
    # JSON export for programmatic processing
    python validate_dataset_quality.py dataset.jsonl --json results.json
    
    # Handle datasets with comment lines
    python validate_dataset_quality.py dataset.jsonl --ignore-comments
    
    # Combine flags
    python validate_dataset_quality.py dataset.jsonl --strict --verbose --json output.json

PROGRAMMATIC USAGE:
    from validate_dataset_quality import DatasetQualityValidator
    
    # Basic validation
    validator = DatasetQualityValidator("dataset.jsonl")
    results = validator.validate()
    
    if results['status'] == 'success':
        print(f"Alignment: {results['prompt_alignment']:.1f}%")
        print(f"Quality Score: {results['content_quality']}/3")
    
    # With options
    validator = DatasetQualityValidator(
        "dataset.jsonl",
        strict=True,        # Conservative alignment matching
        verbose=True,       # Detailed output
        ignore_comments=True
    )
    results = validator.validate()
    
    # Access detailed results
    print(f"Domains: {results.get('domains', {})}")
    print(f"Tool Assessment: {results.get('tool_assessment')}")

EXIT CODES:
    0 - Quality validation completed (check results for assessment)
    1 - Validation failed or error occurred

ALIGNMENT MODES:
    Default (~88%): Permissive matching with generic support patterns
                    Detects quality support responses across domains
    
    --strict (~50%): Conservative keyword-only domain matching
                    Requires domain-specific vocabulary in conversations
                    Useful for validating domain expertise

PARAMETERS:
    --strict            Use strict keyword-only alignment matching (conservative)
    --verbose, -v       Show detailed per-conversation analysis
    --json <file>       Export results to JSON file
    --ignore-comments   Skip lines starting with // or # (non-standard extension)
"""

import json
import sys
import re
import argparse
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Set

# Ensure proper UTF-8 encoding for console output on Windows
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
    import io
    if not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    if not isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


class DatasetQualityValidator:
    """
    Validates content quality and appropriateness of JSONL voice agent datasets.
    
    This validator performs quality checks to assess whether system prompts,
    tool definitions, and conversation content are appropriate and well-aligned.
    Run AFTER DatasetConsistencyValidator passes.
    
    Attributes:
        dataset_path (Path): Path to JSONL file or folder containing JSONL
        jsonl_path (Path): Resolved path to the JSONL file
        folder_path (Path): Folder containing the JSONL
        entries (list): Loaded JSON entries from the JSONL file
        insights (list): Positive findings about the dataset
        warnings (list): Quality concerns to review
        strict_mode (bool): Use conservative keyword-only alignment matching
        verbose_mode (bool): Enable detailed per-conversation output
        ignore_comments (bool): Whether to skip comment lines
        detailed_results (list): Per-conversation analysis results (when verbose=True)
    
    Example:
        >>> validator = DatasetQualityValidator("dataset.jsonl", strict=True)
        >>> results = validator.validate()
        >>> if results['prompt_alignment'] >= 70:
        ...     print("Good alignment")
    """
    
    def __init__(self, dataset_path: str, strict: bool = False, verbose: bool = False, ignore_comments: bool = False):
        """
        Initialize validator with dataset path and options.
        
        Args:
            dataset_path: Path to .jsonl file or folder containing dataset
            strict: If True, use conservative keyword-only alignment matching.
                   Default permissive mode includes generic support patterns (~88%).
                   Strict mode requires domain-specific vocabulary (~50%).
            verbose: If True, show detailed per-conversation analysis
            ignore_comments: If True, skip lines starting with // or #
        
        Raises:
            ValueError: If path is invalid or multiple JSONL files found in folder
        """
        self.dataset_path = Path(dataset_path)
        self.jsonl_path = None
        self.folder_path = None
        self.entries = []
        self.insights = []
        self.warnings = []
        self.strict_mode = strict
        self.verbose_mode = verbose
        self.ignore_comments = ignore_comments
        self.detailed_results = []  # For verbose output
        
        # Determine if path is file or folder
        if self.dataset_path.is_file() and self.dataset_path.suffix == '.jsonl':
            self.jsonl_path = self.dataset_path
            self.folder_path = self.dataset_path.parent
        elif self.dataset_path.is_dir():
            self.folder_path = self.dataset_path
            jsonl_files = list(self.folder_path.glob('*.jsonl'))
            if not jsonl_files:
                raise ValueError(f"No JSONL file found in {self.folder_path}")
            if len(jsonl_files) > 1:
                raise ValueError(f"Multiple JSONL files found. Please specify the file.")
            self.jsonl_path = jsonl_files[0]
        else:
            raise ValueError(f"Path must be a .jsonl file or directory")
    
    def validate(self) -> Dict:
        """
        Run all quality validation checks.
        
        Executes the following checks:
        1. System prompt relevance validation
        2. Tool definition appropriateness validation
        3. Content quality metrics analysis
        
        Returns:
            dict: Validation results with the following structure:
                {
                    'status': 'success' | 'failed',
                    'prompt_alignment': float,  # Percentage (0-100)
                    'aligned_count': int,
                    'unaligned_count': int,
                    'domains': dict,  # Domain breakdown
                    'tool_assessment': str,  # 'correct' | 'needs_review' | 'good' | 'mixed'
                    'action_requests': int,
                    'content_quality': int,  # Score 0-3
                    'total_conversations': int,
                    'total_entries': int,
                    'detailed_results': list  # Only if verbose=True
                }
        
        Example:
            >>> validator = DatasetQualityValidator("dataset.jsonl")
            >>> results = validator.validate()
            >>> if results['prompt_alignment'] >= 70:
            ...     print("Dataset has good prompt alignment")
            >>> if results['tool_assessment'] == 'correct':
            ...     print("Tool definitions are appropriate")
        """
        print("=" * 80)
        print(f"  DATASET QUALITY VALIDATION")
        print(f"  Dataset: {self.jsonl_path.name}")
        print("=" * 80)
        
        # Load entries
        if not self._load_entries():
            return {'status': 'failed', 'reason': 'Failed to load entries'}
        
        # Run quality checks
        prompt_results = self._validate_system_prompt_relevance()
        tool_results = self._validate_tool_definitions()
        content_results = self._analyze_content_quality()
        
        # Print summary
        self._print_summary(prompt_results, tool_results, content_results)
        
        return {
            'status': 'success',
            'prompt_alignment': prompt_results,
            'tool_appropriateness': tool_results,
            'content_quality': content_results
        }
    
    def _load_entries(self) -> bool:
        """Load JSONL entries."""
        try:
            with open(self.jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Skip comment lines if flag is set
                    if self.ignore_comments and (line.startswith('//') or line.startswith('#')):
                        continue
                    
                    self.entries.append(json.loads(line))
            return True
        except Exception as e:
            print(f"\n❌ ERROR: Failed to load entries: {str(e)}")
            return False
    
    def _validate_system_prompt_relevance(self) -> Dict:
        """
        Validate system prompt alignment with conversation content.
        
        Analyzes each conversation to determine if the system_prompt aligns
        with the actual question/answer content using domain detection and
        keyword matching.
        
        Returns:
            dict: {
                'aligned': int,
                'unaligned': int,
                'alignment_percentage': float,
                'domains': dict  # Domain breakdown
            }
        """
        print("\n✓ 1. SYSTEM PROMPT RELEVANCE")
        print("-" * 80)
        
        if not self.entries:
            return {'status': 'skipped'}
        
        # Group by conversation
        conversations = defaultdict(list)
        for entry in self.entries:
            conv_id = entry.get('conversationID', 'unknown')
            conversations[conv_id].append(entry)
        
        aligned = 0
        unaligned = 0
        domain_stats = defaultdict(lambda: {'total': 0, 'aligned': 0, 'category': 'general_advisory'})
        category_stats = defaultdict(lambda: {'total': 0, 'aligned': 0})
        
        for conv_id, entries in conversations.items():
            first_turn = entries[0]
            prompt = first_turn.get('system_prompt', '').lower()
            question = first_turn.get('Question', '').lower()
            answer = first_turn.get('Answer', '').lower()
            
            # Identify domain and category from system prompt
            domain, category = self._identify_domain(prompt)
            
            # Check alignment
            is_aligned = self._check_domain_alignment(domain, question, answer)
            
            domain_stats[domain]['total'] += 1
            domain_stats[domain]['category'] = category
            category_stats[category]['total'] += 1
            if is_aligned:
                aligned += 1
                domain_stats[domain]['aligned'] += 1
                category_stats[category]['aligned'] += 1
            else:
                unaligned += 1
            
            # Store for verbose output
            if self.verbose_mode:
                self.detailed_results.append({
                    'conversation_id': conv_id,
                    'domain': domain,
                    'category': category,
                    'aligned': is_aligned,
                    'question_preview': first_turn.get('Question', '')[:80],
                    'prompt_preview': prompt[:100]
                })
        
        total_conv = len(conversations)
        alignment_pct = (aligned / total_conv * 100) if total_conv > 0 else 0
        
        mode_indicator = " (STRICT MODE)" if self.strict_mode else ""
        print(f"  Total conversations: {total_conv}{mode_indicator}")
        print(f"  Aligned: {aligned}/{total_conv} ({alignment_pct:.1f}%)")
        print(f"  Needs review: {unaligned}/{total_conv} ({100-alignment_pct:.1f}%)")
        
        # Category breakdown
        print(f"\n  Category Breakdown:")
        for cat in ["customer_service", "voice_agent", "general_advisory"]:
            stats = category_stats.get(cat, {'total': 0, 'aligned': 0})
            if stats['total'] == 0:
                continue
            label = self.CATEGORY_LABELS.get(cat, cat)
            cpct = (stats['aligned'] / stats['total'] * 100) if stats['total'] > 0 else 0
            cov = (stats['total'] / total_conv * 100) if total_conv > 0 else 0
            print(f"    {label}: {stats['total']} convos ({cov:.0f}% of dataset) - {cpct:.0f}% aligned")
        
        # Domain breakdown grouped by category
        print(f"\n  Domain Breakdown:")
        for cat in ["customer_service", "voice_agent", "general_advisory"]:
            cat_domains = {d: s for d, s in domain_stats.items() if s['category'] == cat}
            if not cat_domains:
                continue
            label = self.CATEGORY_LABELS.get(cat, cat)
            print(f"\n    {label}:")
            for domain, stats in sorted(cat_domains.items(), key=lambda x: x[1]['total'], reverse=True):
                pct = (stats['aligned'] / stats['total'] * 100) if stats['total'] > 0 else 0
                print(f"      {domain}: {stats['total']} conversations ({stats['aligned']} aligned - {pct:.0f}%)")
        
        if alignment_pct >= 70:
            print(f"\n  GOOD: {alignment_pct:.1f}% alignment indicates strong prompt-content matching")
        elif alignment_pct >= 50:
            print(f"\n  MODERATE: {alignment_pct:.1f}% alignment - consider reviewing prompts")
        else:
            print(f"\n  LOW: {alignment_pct:.1f}% alignment - prompts may not match conversations")
        
        # Verbose output
        if self.verbose_mode and self.detailed_results:
            print(f"\n  DETAILED PER-CONVERSATION RESULTS:")
            for result in self.detailed_results:
                status = "[OK]" if result['aligned'] else "[!!]"
                cat_label = self.CATEGORY_LABELS.get(result['category'], result['category'])
                print(f"    {status} {result['conversation_id']} ({result['domain']} | {cat_label})")
                if not result['aligned']:
                    print(f"       Q: {result['question_preview']}...")
        
        return {
            'total_conversations': total_conv,
            'aligned': aligned,
            'unaligned': unaligned,
            'alignment_percentage': alignment_pct,
            'domains': dict(domain_stats),
            'categories': dict(category_stats)
        }
    
    # ── Domain Registry ────────────────────────────────────────────────────
    # Data-driven domain configuration. Each entry defines:
    #   category       : "customer_service" | "voice_agent" | "general_advisory"
    #   prompt_pattern : regex matched against system_prompt (case-insensitive)
    #   question_kw    : regex matched against questions for strict alignment
    #
    # To add a domain: append a new dict entry — no code changes needed.
    # Order matters: first match wins, so place specific patterns before
    # broad catch-all patterns (e.g., General Service Hotline last).
    # ────────────────────────────────────────────────────────────────────────

    DOMAIN_REGISTRY = [
        # ── Customer Service domains ──────────────────────────────────────
        {
            "name": "Smart Home Tech Support",
            "category": "customer_service",
            "prompt_pattern": r"smart home|iot device|home theater|home entertainment",
            "question_kw": r"smart|light|device|iot|wifi|thermostat|camera|speaker|sensor|doorbell|vacuum|motion|alert|soundbar|hdmi|tv|arc"
        },
        {
            "name": "Electric Vehicle Support",
            "category": "customer_service",
            "prompt_pattern": r"electric vehicle|\bev\b|connected car",
            "question_kw": r"car|vehicle|ev|navigation|touchscreen|bluetooth|charge|battery|drive|cruise|lane|assist|voice command|address|accent"
        },
        {
            "name": "Banking Service Hotline",
            "category": "customer_service",
            "prompt_pattern": r"bank|banking|account.*service|financial.*service",
            "question_kw": r"account|balance|transfer|transaction|overdraft|loan|statement|card|atm|deposit|withdraw"
        },
        {
            "name": "Insurance Service Hotline",
            "category": "customer_service",
            "prompt_pattern": r"insurance|policy|claim|underwrit",
            "question_kw": r"claim|policy|premium|coverage|deductible|renewal|beneficiary|accident|reimburse"
        },
        {
            "name": "Telecom Service Hotline",
            "category": "customer_service",
            "prompt_pattern": r"telecom|mobile.*plan|phone.*plan|internet.*provider|broadband",
            "question_kw": r"plan|data|roaming|signal|bill|upgrade|outage|coverage|sim|network"
        },
        {
            "name": "Healthcare Service Line",
            "category": "customer_service",
            "prompt_pattern": r"healthcare|medical.*support|patient.*service|appointment.*schedul",
            "question_kw": r"appointment|prescription|referral|symptom|doctor|copay|lab|test result|insurance|bill"
        },
        {
            "name": "Airline Customer Service",
            "category": "customer_service",
            "prompt_pattern": r"airline|flight.*support|booking.*support|travel.*support",
            "question_kw": r"flight|booking|cancel|delay|baggage|seat|boarding|refund|check.in|luggage"
        },
        {
            "name": "Utilities Service Hotline",
            "category": "customer_service",
            "prompt_pattern": r"utilit|power.*company|water.*service|electric.*company|energy.*provider",
            "question_kw": r"bill|outage|meter|usage|disconnect|service|payment|rate|power"
        },
        {
            "name": "Cybersecurity",
            "category": "customer_service",
            "prompt_pattern": r"cybersecurity|password|phishing",
            "question_kw": r"password|security|phish|hack|safe|credential|breach|encrypt|virus|malware"
        },
        {
            "name": "Air Quality",
            "category": "customer_service",
            "prompt_pattern": r"air quality|indoor air",
            "question_kw": r"air|quality|ventilation|filter|purif|monitor|sensor|particulate"
        },
        # Catch-all for generic service/support prompts — must come after
        # specific service domains to avoid stealing their matches.
        {
            "name": "General Service Hotline",
            "category": "customer_service",
            "prompt_pattern": r"(customer|technical|product).*(support|service|hotline|helpdesk|help desk|call center)",
            "question_kw": r"issue|problem|help|resolve|ticket|case|escalat|status|account|return|refund|warranty"
        },
        # ── Voice Agent domains ───────────────────────────────────────────
        {
            "name": "Language Learning",
            "category": "voice_agent",
            "prompt_pattern": r"language learning|learn.*language",
            "question_kw": r"learn|language|vocabulary|grammar|practice|fluent|pronounc|speak|spanish|french"
        },
        {
            "name": "Fitness Coach",
            "category": "voice_agent",
            "prompt_pattern": r"fitness|workout|exercise.*coach|personal.*train",
            "question_kw": r"workout|exercise|rep|set|warm.up|stretch|muscle|routine|cardio|squat"
        },
        {
            "name": "Travel Concierge",
            "category": "voice_agent",
            "prompt_pattern": r"travel.*concierge|trip.*plan|itinerary|travel.*assist",
            "question_kw": r"trip|destination|hotel|flight|itinerary|recommend|visit|book|travel|resort"
        },
        {
            "name": "Cooking Assistant",
            "category": "voice_agent",
            "prompt_pattern": r"cook|recipe|chef|meal.*plan",
            "question_kw": r"recipe|ingredient|cook|bake|prep|minute|temperature|serve|stir|chop"
        },
        {
            "name": "Personal Finance Advisor",
            "category": "voice_agent",
            "prompt_pattern": r"budget|financial.*plan|saving.*goal|money.*manag",
            "question_kw": r"budget|save|spend|debt|invest|goal|expense|income|retire|fund"
        },
        {
            "name": "Public Speaking Coach",
            "category": "voice_agent",
            "prompt_pattern": r"public.*speak|presentation.*coach|speech.*coach",
            "question_kw": r"speak|presentation|audience|nervous|stage|confidence|body language|voice|talk"
        },
        {
            "name": "Meditation Guide",
            "category": "voice_agent",
            "prompt_pattern": r"meditat|mindful|breathing.*exercis|relaxat.*guide",
            "question_kw": r"meditat|mindful|breath|relax|calm|posture|focus|stress|anxious"
        },
        {
            "name": "Event Finder",
            "category": "voice_agent",
            "prompt_pattern": r"event.*find|activit.*recommend|local.*suggest|things.*to.*do",
            "question_kw": r"event|activity|weekend|local|happen|suggest|hike|outdoor|nearby"
        },
        {
            "name": "Podcast Recommender",
            "category": "voice_agent",
            "prompt_pattern": r"podcast.*recommend|podcast.*suggest|podcast.*assist",
            "question_kw": r"podcast|episode|listen|show|recommend|genre|series|host"
        },
        # ── General Advisory domains ──────────────────────────────────────
        {
            "name": "Fountain Pen Care",
            "category": "general_advisory",
            "prompt_pattern": r"fountain pen",
            "question_kw": r"pen|ink|nib|skip|flow|cartridge|write"
        },
        {
            "name": "Comedy Writing",
            "category": "general_advisory",
            "prompt_pattern": r"stand-up comedy|joke|humor",
            "question_kw": r"joke|comedy|funny|punchline|premise|laugh"
        },
        {
            "name": "Gardening",
            "category": "general_advisory",
            "prompt_pattern": r"garden|plant|soil",
            "question_kw": r"plant|garden|soil|grow|seed|weed|water|pest|leaf|yellow"
        },
        {
            "name": "Coffee",
            "category": "general_advisory",
            "prompt_pattern": r"coffee|brew|espresso",
            "question_kw": r"coffee|brew|bean|grind|roast|espresso"
        },
        {
            "name": "Coding/Programming",
            "category": "general_advisory",
            "prompt_pattern": r"coding|programming|software",
            "question_kw": r"code|program|variable|function|class|syntax|debug|error"
        },
        {
            "name": "Board Games",
            "category": "general_advisory",
            "prompt_pattern": r"board game|game rules",
            "question_kw": r"game|board|rules|play|turn|dice|card|settlement|build"
        },
        {
            "name": "Vintage Clothing",
            "category": "general_advisory",
            "prompt_pattern": r"vintage.*cloth|fashion|thrift",
            "question_kw": r"vintage|cloth|fabric|wash|care|silk|quality|thrift|damage"
        },
        {
            "name": "Astronomy",
            "category": "general_advisory",
            "prompt_pattern": r"astronomy|telescope|star.*gaz",
            "question_kw": r"telescope|star|planet|celestial|sky|observe|milky way"
        },
        {
            "name": "Pet Training",
            "category": "general_advisory",
            "prompt_pattern": r"pet.*train|dog.*behav|dog.*train",
            "question_kw": r"dog|leash|pull|bark|train|command|treat|walk|behav"
        },
        {
            "name": "Music Theory",
            "category": "general_advisory",
            "prompt_pattern": r"music.*theory|music.*tutor|scale|chord",
            "question_kw": r"scale|chord|note|key|major|minor|music|melody|rhythm"
        },
        {
            "name": "DIY / Home Repair",
            "category": "general_advisory",
            "prompt_pattern": r"diy|furniture.*assembl|home.*repair|handyman",
            "question_kw": r"assembl|tool|screw|drill|nail|fix|repair|install|build|cam lock"
        },
        {
            "name": "Songwriting",
            "category": "general_advisory",
            "prompt_pattern": r"songwrit|lyric|composing.*music",
            "question_kw": r"lyric|melody|song|write|verse|chorus|rhyme|hook"
        },
        {
            "name": "Home Canning / Preserving",
            "category": "general_advisory",
            "prompt_pattern": r"canning|preserv|jam|pickle",
            "question_kw": r"jar|can|seal|boil|jam|pickle|preserve|lid|water.bath"
        },
        {
            "name": "Bike Repair",
            "category": "general_advisory",
            "prompt_pattern": r"bike.*repair|bicycle|cycling.*maint",
            "question_kw": r"tire|brake|chain|pedal|gear|pump|wheel|flat|lubric"
        },
        {
            "name": "Cryptocurrency Basics",
            "category": "general_advisory",
            "prompt_pattern": r"cryptocurrenc|bitcoin|blockchain|crypto.*invest",
            "question_kw": r"crypto|wallet|bitcoin|token|blockchain|volatile|hodl|exchange"
        },
        {
            "name": "Car Detailing",
            "category": "general_advisory",
            "prompt_pattern": r"car.*detail|car.*clean|auto.*detail",
            "question_kw": r"clean|stain|interior|wax|polish|upholster|dashboard|cup holder"
        },
        {
            "name": "Soldering / Electronics",
            "category": "general_advisory",
            "prompt_pattern": r"solder|electron.*project|circuit",
            "question_kw": r"solder|iron|wire|component|circuit|flux|tin|joint"
        },
        {
            "name": "Pottery / Clay Work",
            "category": "general_advisory",
            "prompt_pattern": r"pottery|clay|ceramic|wedg",
            "question_kw": r"clay|pottery|wedg|wheel|kiln|glaze|air bubble|mold|shape"
        },
        {
            "name": "Watch Repair",
            "category": "general_advisory",
            "prompt_pattern": r"watch.*batter|watch.*repair|horology",
            "question_kw": r"watch|battery|case.*back|tool|replace|crystal|strap|movement"
        },
        {
            "name": "Graphic Design",
            "category": "general_advisory",
            "prompt_pattern": r"graphic.*design|layout|font.*pair|present.*design",
            "question_kw": r"font|color|layout|design|slide|white space|palette|visual"
        },
    ]

    # Category display labels and emoji
    CATEGORY_LABELS = {
        "customer_service": "🎧 Customer Service",
        "voice_agent":      "🤖 Voice Agent",
        "general_advisory": "💬 General Advisory",
    }

    def _identify_domain(self, prompt: str) -> Tuple[str, str]:
        """
        Identify domain and category from system prompt.

        Returns:
            Tuple of (domain_name, category). Falls back to
            ("Other/Diverse", "general_advisory") when no pattern matches.
        """
        for entry in self.DOMAIN_REGISTRY:
            if re.search(entry["prompt_pattern"], prompt, re.IGNORECASE):
                return entry["name"], entry["category"]
        return "Other/Diverse", "general_advisory"

    def _check_domain_alignment(self, domain: str, question: str, answer: str) -> bool:
        """Check if question/answer align with domain."""
        # In strict mode, skip generic patterns - only match domain keywords
        if not self.strict_mode:
            # Generic support patterns that work across domains
            if re.search(r'(let\'?s|can help|suggest|recommend|try|first|start)', answer, re.IGNORECASE):
                if len(answer) > 100:  # Substantial support response
                    return True

        # Look up question keywords from registry
        for entry in self.DOMAIN_REGISTRY:
            if entry["name"] == domain:
                return bool(re.search(entry["question_kw"], question, re.IGNORECASE))

        return False  # Conservative for unknown domains
    
    def _validate_tool_definitions(self) -> Dict:
        """
        Validate tool definition appropriateness based on question intent.
        
        Classifies questions as:
        - Action requests: Questions asking agent to DO something (need tools)
        - Instructional: "How do I..." questions (conversational, no tools)
        - General: Problem descriptions, follow-ups (conversational)
        
        Returns:
            dict: {
                'with_tools': int,
                'without_tools': int,
                'action_requests': int,
                'instructional': int,
                'general': int,
                'assessment': 'correct' | 'needs_review' | 'good' | 'mixed'
            }
        """
        print("\n✓ 2. TOOL DEFINITION APPROPRIATENESS")
        print("-" * 80)
        
        if not self.entries:
            return {'status': 'skipped'}
        
        # Check current state
        with_tools = sum(1 for e in self.entries if e.get('tool_definitions'))
        without_tools = len(self.entries) - with_tools
        
        print(f"  Entries with tool_definitions: {with_tools}")
        print(f"  Entries without tool_definitions: {without_tools}")
        
        # Analyze question intents
        action_requests = 0
        instructional = 0
        general = 0
        
        action_samples = []
        
        for entry in self.entries:
            question = entry.get('Question', '').lower()
            
            # Direct action request patterns
            if re.match(r'^(turn on|turn off|set my|change my|adjust my|enable my|disable my|restart my|update my)', question):
                action_requests += 1
                action_samples.append(entry)
            elif re.search(r'^(can you|could you|please|would you) (turn|set|change|adjust|enable|disable)', question):
                action_requests += 1
                action_samples.append(entry)
            # Instructional patterns
            elif re.search(r'(how do i|how can i|how should i|what\'?s the process|is there a (way|setting)|should i|can i create)', question):
                instructional += 1
            else:
                general += 1
        
        total = len(self.entries)
        print(f"\n  Question Intent Classification:")
        print(f"    • Action Requests (need tools): {action_requests} ({action_requests/total*100:.1f}%)")
        print(f"    • Instructional/Guidance: {instructional} ({instructional/total*100:.1f}%)")
        print(f"    • General Conversation: {general} ({general/total*100:.1f}%)")
        
        # Assessment
        if action_requests == 0 and without_tools == total:
            print(f"\n  ✅ CORRECT: No action requests detected. NULL tool_definitions is appropriate.")
            print(f"     Dataset is conversational/instructional support.")
            assessment = "correct"
        elif action_requests > 0 and without_tools == total:
            print(f"\n  ⚠  REVIEW: {action_requests} action requests detected but no tool_definitions.")
            print(f"     Consider adding tool definitions for production scenarios.")
            if action_samples:
                print(f"\n     Sample action requests:")
                for sample in action_samples[:3]:
                    q_preview = sample.get('Question', '')[:80]
                    print(f"       - {sample.get('conversationID')}: {q_preview}...")
            assessment = "needs_review"
        elif action_requests > 0 and with_tools > 0:
            print(f"\n  ✅ GOOD: Action requests have corresponding tool_definitions.")
            assessment = "good"
        else:
            print(f"\n  ℹ  INFO: Mixed dataset with both conversational and tool-based interactions.")
            assessment = "mixed"
        
        return {
            'with_tools': with_tools,
            'without_tools': without_tools,
            'action_requests': action_requests,
            'instructional': instructional,
            'general': general,
            'assessment': assessment
        }
    
    def _analyze_content_quality(self) -> Dict:
        """
        Analyze content quality metrics.
        
        Assesses:
        - Question/answer length appropriateness
        - System prompt diversity
        - Overall content depth
        
        Returns:
            dict: {
                'avg_question_length': float,
                'avg_answer_length': float,
                'unique_prompts': int,
                'total_conversations': int,
                'total_entries': int,
                'quality_score': int  # 0-3 scale
            }
        """
        print("\n✓ 3. CONTENT QUALITY METRICS")
        print("-" * 80)
        
        if not self.entries:
            return {'status': 'skipped'}
        
        # Calculate metrics
        question_lengths = [len(e.get('Question', '')) for e in self.entries]
        answer_lengths = [len(e.get('Answer', '')) for e in self.entries]
        
        avg_q_len = sum(question_lengths) / len(question_lengths) if question_lengths else 0
        avg_a_len = sum(answer_lengths) / len(answer_lengths) if answer_lengths else 0
        
        # Count unique system prompts
        unique_prompts = len(set(e.get('system_prompt', '') for e in self.entries))
        
        # Count conversations
        conversations = set(e.get('conversationID', '') for e in self.entries)
        
        print(f"  Average Question length: {avg_q_len:.0f} characters")
        print(f"  Average Answer length: {avg_a_len:.0f} characters")
        print(f"  Unique system prompts: {unique_prompts}")
        print(f"  Total conversations: {len(conversations)}")
        print(f"  Total entries: {len(self.entries)}")
        
        # Quality assessment
        quality_score = 0
        issues = []
        
        if avg_q_len < 20:
            issues.append("Questions are very short (< 20 chars)")
        elif avg_q_len > 50:
            quality_score += 1
        
        if avg_a_len < 100:
            issues.append("Answers are short (< 100 chars)")
        elif avg_a_len > 300:
            quality_score += 1
        
        if unique_prompts > len(conversations) * 0.3:
            quality_score += 1
        
        print(f"\n  Quality Assessment:")
        if quality_score >= 2:
            print(f"  ✅ GOOD: Content has good depth and diversity")
        elif quality_score == 1:
            print(f"  ⚠  MODERATE: Some quality concerns")
        else:
            print(f"  ❌ NEEDS IMPROVEMENT: Quality issues detected")
        
        if issues:
            print(f"\n  Issues detected:")
            for issue in issues:
                print(f"    • {issue}")
        
        return {
            'avg_question_length': avg_q_len,
            'avg_answer_length': avg_a_len,
            'unique_prompts': unique_prompts,
            'total_conversations': len(conversations),
            'total_entries': len(self.entries),
            'quality_score': quality_score
        }
    
    def _print_summary(self, prompt_results: Dict, tool_results: Dict, content_results: Dict):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print("  QUALITY VALIDATION SUMMARY")
        print("=" * 80)
        
        print(f"\n  📊 Key Metrics:")
        
        # Prompt alignment
        if 'alignment_percentage' in prompt_results:
            pct = prompt_results['alignment_percentage']
            status = "✅" if pct >= 70 else "⚠" if pct >= 50 else "❌"
            print(f"    {status} System Prompt Alignment: {pct:.1f}%")
        
        # Tool appropriateness
        if 'assessment' in tool_results:
            assessment = tool_results['assessment']
            status = "✅" if assessment in ['correct', 'good'] else "⚠"
            print(f"    {status} Tool Definitions: {assessment}")
        
        # Content quality
        if 'quality_score' in content_results:
            score = content_results['quality_score']
            status = "✅" if score >= 2 else "⚠" if score == 1 else "❌"
            print(f"    {status} Content Quality: {score}/3")
        
        print(f"\n  📋 Dataset Characteristics:")
        print(f"    • Conversations: {content_results.get('total_conversations', 0)}")
        print(f"    • Entries: {content_results.get('total_entries', 0)}")
        print(f"    • Domain diversity: {len(prompt_results.get('domains', {}))} domains")
        print(f"    • Action-oriented: {tool_results.get('action_requests', 0)} action requests")
        print(f"    • Instructional: {tool_results.get('instructional', 0)} how-to questions")
        
        print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Validate JSONL dataset quality',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python validate_dataset_quality.py dataset.jsonl
  python validate_dataset_quality.py dataset.jsonl --strict
  python validate_dataset_quality.py dataset.jsonl --verbose --json results.json
        """
    )
    
    parser.add_argument('dataset_path', help='Path to JSONL file or dataset folder')
    parser.add_argument('--strict', action='store_true', 
                       help='Use strict keyword-only alignment matching (more conservative)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Show detailed per-conversation analysis')
    parser.add_argument('--json', metavar='FILE',
                       help='Export results to JSON file')
    parser.add_argument('--ignore-comments', action='store_true',
                       help='Skip lines starting with // or # (non-standard JSONL extension)')
    
    args = parser.parse_args()
    
    try:
        validator = DatasetQualityValidator(args.dataset_path, 
                                           strict=args.strict, 
                                           verbose=args.verbose,
                                           ignore_comments=args.ignore_comments)
        results = validator.validate()
        
        # Export to JSON if requested
        if args.json:
            output_path = Path(args.json)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"\n📄 Results exported to: {output_path}")
        
        sys.exit(0 if results['status'] == 'success' else 1)
    except Exception as e:
        print(f"\n❌ VALIDATION ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
