
if __name__ == "__main__":
    from sbmlutils.converters.cellml.cellml_simulator import run_cellml_timecourse

    # converted models
    model_names = [
        "glimepiride_kidney",
        "glimepiride_liver",
        "glimepiride_intestine",
        "glimepiride_body",
        "glimepiride_body_flat",
    ]
    for name in model_names:
        sbml_path = Path(__file__).parent / "models" / f"{name}.xml"
        cellml_path = sbml_path.parent / f"{sbml_path.stem}.cellml"
        model: libcellml.Model = convert_sbml2cellml(sbml_path=sbml_path)
        write_model_to_file(model=model, cellml_path=cellml_path)
        run_cellml_timecourse(cellml_path)