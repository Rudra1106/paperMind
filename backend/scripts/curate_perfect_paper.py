import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.supabase_client import get_supabase
from app.services import paper_store

async def main():
    pdf_hash = "18e1b007a1dab45b30cc861ba2dfda25"
    
    supabase = get_supabase()
    
    # 1. Fetch existing paper to get ID and storage path
    existing = await paper_store.get_paper_by_hash(pdf_hash)
    if not existing:
        print("Paper not found in DB. Run seed_demo_paper.py first.")
        return
        
    paper_id = existing["id"]
    storage_path = existing["storage_path"]
    
    # 2. Perfect concepts array
    concepts = [
        {
            "name": "RNN Limitations",
            "canonical_name": "rnn_limitations",
            "aliases": ["Recurrent Neural Network bottlenecks", "sequential computation limit"],
            "category": "prerequisite",
            "definition": "Recurrent Neural Networks (RNNs) process sequences one step at a time, preventing parallelization and struggling with long-range dependencies due to vanishing gradients. This sequential bottleneck is the core problem the Transformer was invented to solve.",
            "resource_urls": [],
            "evidence_quote": "Sequential computation precludes parallelization within training examples, which becomes critical at longer sequence lengths."
        },
        {
            "name": "Attention Mechanism",
            "canonical_name": "attention_mechanism",
            "aliases": ["Bahdanau attention", "global attention"],
            "category": "prerequisite",
            "definition": "A mechanism that allows a model to selectively focus on different parts of the input sequence when producing an output, allowing every position to 'look at' every other position directly instead of passing information step by step.",
            "resource_urls": [],
            "evidence_quote": "Attention mechanisms have become an integral part of compelling sequence modeling and transduction models in various tasks, allowing modeling of dependencies without regard to their distance in the input or output sequences."
        },
        {
            "name": "Scaled Dot-Product Attention",
            "canonical_name": "scaled_dot_product_attention",
            "aliases": ["QKV attention"],
            "category": "new",
            "definition": "The mathematical core of the Transformer. It computes attention weights by taking the dot product of a Query (Q) and Key (K), scaling by 1/√d_k to prevent vanishing gradients in the softmax, and multiplying by the Value (V).",
            "resource_urls": [],
            "evidence_quote": "We call our particular attention 'Scaled Dot-Product Attention'. We compute the dot products of the query with all keys, divide each by √dk, and apply a softmax function to obtain the weights on the values."
        },
        {
            "name": "Multi-Head Attention",
            "canonical_name": "multi_head_attention",
            "aliases": ["parallel attention heads"],
            "category": "new",
            "definition": "Instead of performing a single attention function, the model runs multiple attention computations in parallel on different learned linear projections of Q, K, and V. This allows the model to jointly attend to information from different representation subspaces (e.g., syntax, semantics).",
            "resource_urls": [],
            "evidence_quote": "Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions."
        },
        {
            "name": "Self-Attention vs Cross-Attention",
            "canonical_name": "self_vs_cross_attention",
            "aliases": ["intra-attention"],
            "category": "new",
            "definition": "In Self-Attention, all of the keys, values and queries come from the same place (e.g., the encoder output). In Cross-Attention, the queries come from the previous decoder layer, and the memory keys and values come from the output of the encoder.",
            "resource_urls": [],
            "evidence_quote": "In 'encoder-decoder attention' layers, the queries come from the previous decoder layer... In an encoder, self-attention layers... keys, values and queries come from the same place."
        },
        {
            "name": "Positional Encoding",
            "canonical_name": "positional_encoding",
            "aliases": ["sinusoidal position embeddings"],
            "category": "new",
            "definition": "Since the Transformer uses no recurrence or convolution, it has no innate sense of token order. Positional encodings (using sine and cosine functions of different frequencies) are injected into the input embeddings to provide relative or absolute position information.",
            "resource_urls": [],
            "evidence_quote": "Since our model contains no recurrence and no convolution, in order for the model to make use of the order of the sequence, we must inject some information about the relative or absolute position of the tokens in the sequence."
        },
        {
            "name": "Encoder-Decoder Stack",
            "canonical_name": "encoder_decoder_stack",
            "aliases": ["Transformer architecture"],
            "category": "new",
            "definition": "The full architecture consists of stacked encoder and decoder layers. Each layer contains multi-head attention and position-wise feed-forward networks, wrapped with residual connections and layer normalization to stabilize deep training.",
            "resource_urls": [],
            "evidence_quote": "The encoder is composed of a stack of N=6 identical layers... The decoder is also composed of a stack of N=6 identical layers."
        },
        {
            "name": "Transformer Payoff",
            "canonical_name": "transformer_payoff",
            "aliases": ["BLEU score improvements"],
            "category": "new",
            "definition": "By parallelizing computation entirely through attention, the Transformer achieved state-of-the-art BLEU scores on translation tasks while requiring significantly less training time and compute cost compared to RNN or CNN baselines.",
            "resource_urls": [],
            "evidence_quote": "On the WMT 2014 English-to-German translation task, the big transformer model achieves a new state-of-the-art BLEU score of 28.4... training on 8 P100 GPUs for 3.5 days."
        }
    ]
    
    # 3. Perfect edges mapping the dependency graph
    edges = {
        "attention_mechanism": ["rnn_limitations"],
        "scaled_dot_product_attention": ["attention_mechanism"],
        "multi_head_attention": ["scaled_dot_product_attention"],
        "self_vs_cross_attention": ["multi_head_attention"],
        "positional_encoding": ["self_vs_cross_attention"],
        "encoder_decoder_stack": ["positional_encoding", "multi_head_attention"],
        "transformer_payoff": ["encoder_decoder_stack"]
    }

    # 4. Update the DB directly using Supabase
    print(f"Updating paper {paper_id} with perfect concepts and edges...")
    res = supabase.table("papers").update({
        "concepts": concepts,
        "edges": edges,
        "title": "Attention Is All You Need"
    }).eq("id", paper_id).execute()
    
    print("Done! Cache is now perfect.")

if __name__ == "__main__":
    asyncio.run(main())
