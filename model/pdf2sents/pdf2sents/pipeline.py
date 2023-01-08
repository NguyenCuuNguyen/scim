from pathlib import Path
from typing import Union
import warnings
from dataclasses import dataclass

import torch
from cached_path import cached_path

from mmda.parsers.pdfplumber_parser import PDFPlumberParser
from mmda.predictors.heuristic_predictors.sentence_boundary_predictor import \
    PysbdSentenceBoundaryPredictor
from mmda.predictors.lp_predictors import LayoutParserPredictor
from mmda.rasterizers.rasterizer import PDF2ImageRasterizer
from mmda.types.document import Document

import springs as sp

from .typed_predictors import TypedBlockPredictor, TypedSentencesPredictor
from .word_predictors import ExtendedDictionaryWordPredictor


@sp.make_flexy
@dataclass
class PipelineStepConfig:
    _target_: str = sp.MISSING


@dataclass
class PipelineConfig:
    parser: PipelineStepConfig = PipelineStepConfig(
        _target_=sp.Target.to_string(PDFPlumberParser)
    )
    rasterizer: PipelineStepConfig = PipelineStepConfig(
        _target_=sp.Target.to_string(PDF2ImageRasterizer)
    )
    layout: PipelineStepConfig = sp.flexy_field(
        PipelineStepConfig,
        _target_=sp.Target.to_string(LayoutParserPredictor.from_pretrained),
        config_path="lp://efficientdet/PubLayNet"
    )
    sents: PipelineStepConfig = PipelineStepConfig(
        _target_=sp.Target.to_string(PysbdSentenceBoundaryPredictor)
    )
    words: PipelineStepConfig = sp.flexy_field(
        PipelineStepConfig,
        _target_=sp.Target.to_string(ExtendedDictionaryWordPredictor),
        dictionary_file_path=str(cached_path(
            'https://github.com/dwyl/english-words/raw/master/words.txt'
        ))
    )
    blocks_type: PipelineStepConfig = PipelineStepConfig(
        _target_=sp.Target.to_string(TypedBlockPredictor)
    )
    sents_type: PipelineStepConfig = PipelineStepConfig(
        _target_=sp.Target.to_string(TypedSentencesPredictor)
    )


class Pipeline:
    def __init__(self, config: PipelineConfig):
        self.parser = sp.init.now(
            config.parser, PDFPlumberParser
        )
        self.rasterizer = sp.init.now(
            config.rasterizer, PDF2ImageRasterizer
        )
        self.layout_pred = sp.init.now(
            config.layout, LayoutParserPredictor
        )
        self.words_pred = sp.init.now(
            config.words, ExtendedDictionaryWordPredictor
        )
        self.sents_pred = sp.init.now(
            config.sents, PysbdSentenceBoundaryPredictor
        )
        self.blocks_type_pred = sp.init.now(
            config.blocks_type, TypedBlockPredictor
        )
        self.sents_type_pred = sp.init.now(
            config.sents_type, TypedSentencesPredictor
        )

    def __call__(self, input_path: Union[Path, str]) -> Document:
        return self.run(input_path)

    def run(self, input_path: Union[Path, str]) -> Document:
        src_path = Path(cached_path(input_path))

        doc = self.parser.parse(str(src_path))
        images = self.rasterizer.rasterize(str(src_path), dpi=72)
        doc.annotate_images(images)

        with torch.no_grad(), warnings.catch_warnings():
            # ignore warnings generated by running PubLayNet. These are:
            # - "UserWarning: Named tensors and all their associated APIs are
            #    an experimental feature and subject to change."
            # - "UserWarning: floor_divide is deprecated, and will be removed
            #   in a future version of pytorch."
            warnings.simplefilter("ignore")
            layout_regions = self.layout_pred.predict(doc)
            doc.annotate(blocks=layout_regions)

        words = self.words_pred.predict(doc)
        doc.annotate(words=words)

        sents = self.sents_pred.predict(doc)
        doc.annotate(sents=sents)

        typed_blocks = self.blocks_type_pred.predict(doc)
        doc.annotate(typed_blocks=typed_blocks)

        typed_sents = self.sents_type_pred.predict(doc)
        doc.annotate(typed_sents=typed_sents)

        return doc
