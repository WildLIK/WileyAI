#include "llama-grammar.h"
#include <fstream>
#include <iostream>
#include <iterator>
#include <string>

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    std::ifstream file(argv[1], std::ios::binary);
    if (!file) return 2;
    std::string source((std::istreambuf_iterator<char>(file)), {});
    llama_grammar *grammar = llama_grammar_init_impl(nullptr, source.c_str(), "root", false, nullptr, 0, nullptr, 0);
    if (!grammar) return 3;
    if (argc > 2) {
        for (const unsigned char c : std::string(argv[2])) {
            llama_grammar_accept(grammar, c);
            if (llama_grammar_get_stacks(grammar).empty()) break;
        }
        bool accepted = false;
        for (const auto &stack : llama_grammar_get_stacks(grammar)) accepted |= stack.empty();
        std::cout << (accepted ? "ACCEPT" : "REJECT") << '\n';
    } else std::cout << "PARSED\n";
    llama_grammar_free_impl(grammar);
    return 0;
}
